from typing import List
from environment import Environment, generate_llm_market_agents
from ziagents import Order, Trade
from plotter import analyze_and_plot_auction_results

from colorama import Fore, Style

class DoubleAuction:
    def __init__(self, environment: Environment, max_rounds: int):
        self.environment = environment
        self.max_rounds = max_rounds
        self.current_round = 0
        self.successful_trades: List[Trade] = []
        self.total_surplus_extracted = 0.0
        self.average_prices: List[float] = []
        self.order_book = []  # Store current order book
        self.trade_history = []  # Store trade history
        self.trade_counter = 0

    def match_orders(self, bids: List[Order], asks: List[Order], round_num: int) -> List[Trade]:
        trades = []
        bids.sort(key=lambda x: x.price, reverse=True)  # Highest bids first
        asks.sort(key=lambda x: x.price)  # Lowest asks first

        while bids and asks and bids[0].price >= asks[0].price:
            bid = bids.pop(0)
            ask = asks.pop(0)
            trade_price = (bid.price + ask.price) / 2  # Midpoint price
            trade_quantity = min(bid.quantity, ask.quantity)
            trade = Trade(
                trade_id=self.trade_counter,
                buyer_id=bid.agent_id,
                seller_id=ask.agent_id,
                quantity=trade_quantity,
                price=trade_price,
                buyer_value=bid.base_value,
                seller_cost=ask.base_cost,
                round=round_num
            )
            trades.append(trade)
            self.trade_counter += 1
            self.order_book.append({'price': trade_price, 'shares': trade_quantity, 'total': trade_price * trade_quantity})  # Update order book
        return trades

    def execute_trades(self, trades: List[Trade]):
        for trade in trades:
            buyer = self.environment.get_agent(trade.buyer_id)
            seller = self.environment.get_agent(trade.seller_id)

            buyer_surplus = trade.buyer_value - trade.price
            seller_surplus = trade.price - trade.seller_cost

            if buyer_surplus < 0 or seller_surplus < 0:
                print(f"Trade rejected due to negative surplus: Buyer Surplus = {buyer_surplus}, Seller Surplus = {seller_surplus}")
                continue

            buyer.finalize_trade(trade)
            seller.finalize_trade(trade)
            self.total_surplus_extracted += buyer_surplus + seller_surplus
            self.average_prices.append(trade.price)
            self.successful_trades.append(trade)
            self.trade_history.append(trade)  # Update trade history

            print(f"Executing trade: Buyer {buyer.zi_agent.id} - Surplus: {buyer_surplus:.2f}, Seller {seller.zi_agent.id} - Surplus: {seller_surplus:.2f}")

    def run_auction(self):
        if self.current_round >= self.max_rounds:
            print("Max rounds reached. Auction has ended.")
            return
        
        for round_num in range(self.current_round + 1, self.max_rounds + 1):
            print(f"\n=== Round {round_num} ===")
            self.current_round = round_num

            # Prepare market info
            market_info = self._get_market_info()

            # Generate bids from buyers
            bids = []
            for buyer in self.environment.buyers:
                if buyer.zi_agent.allocation.goods < buyer.zi_agent.preference_schedule.values.get(len(buyer.zi_agent.preference_schedule.values), 0):
                    bid = buyer.generate_bid(market_info)
                    if bid:
                        bids.append(bid)
                        print(f"{Fore.BLUE}Buyer {Fore.CYAN}{buyer.zi_agent.id}{Fore.BLUE} bid: ${Fore.GREEN}{bid.price:.2f}{Fore.BLUE} for {Fore.YELLOW}{bid.quantity}{Fore.BLUE} unit(s){Style.RESET_ALL}")

            # Generate asks from sellers
            asks = []
            for seller in self.environment.sellers:
                if seller.zi_agent.allocation.goods > 0:
                    ask = seller.generate_bid(market_info)
                    if ask:
                        asks.append(ask)
                        print(f"{Fore.RED}Seller {Fore.CYAN}{seller.zi_agent.id}{Fore.RED} ask: ${Fore.GREEN}{ask.price:.2f}{Fore.RED} for {Fore.YELLOW}{ask.quantity}{Fore.RED} unit(s){Style.RESET_ALL}")

            trades = self.match_orders(bids, asks, round_num)
            if trades:
                self.execute_trades(trades)
            self.current_round += 1

        self.summarize_results()

    def _get_market_info(self) -> dict:
        last_trade_price = self.average_prices[-1] if self.average_prices else None
        average_price = sum(self.average_prices) / len(self.average_prices) if self.average_prices else None
        
        # If no trades have occurred, use the midpoint of buyer and seller base values
        if last_trade_price is None or average_price is None:
            buyer_base_value = max(agent.zi_agent.preference_schedule.get_value(1) for agent in self.environment.buyers)
            seller_base_value = min(agent.zi_agent.preference_schedule.get_value(1) for agent in self.environment.sellers)
            initial_price_estimate = (buyer_base_value + seller_base_value) / 2
            
            last_trade_price = last_trade_price or initial_price_estimate
            average_price = average_price or initial_price_estimate

        return {
            "last_trade_price": last_trade_price,
            "average_price": average_price,
            "total_trades": len(self.successful_trades),
            "current_round": self.current_round,
        }

    def summarize_results(self):
        total_trades = len(self.successful_trades)
        avg_price = sum(self.average_prices) / total_trades if total_trades > 0 else 0

        print(f"\n=== Auction Summary ===")
        print(f"Total Successful Trades: {total_trades}")
        print(f"Total Surplus Extracted: {self.total_surplus_extracted:.2f}")
        print(f"Average Price: {avg_price:.2f}")

        # Compare theoretical and practical surplus
        ce_price, ce_quantity, theoretical_buyer_surplus, theoretical_seller_surplus, theoretical_total_surplus = self.environment.calculate_equilibrium()
        print(f"\n=== Theoretical vs. Practical Surplus ===")
        print(f"Theoretical Total Surplus: {theoretical_total_surplus:.2f}")
        print(f"Practical Total Surplus: {self.total_surplus_extracted:.2f}")
        print(f"Difference (Practical - Theoretical): {self.total_surplus_extracted - theoretical_total_surplus:.2f}")

        # Detecting and explaining potential negative surplus
        if self.total_surplus_extracted < 0:
            print(f"Warning: Negative practical surplus detected. Possible causes include:")
            print(f"  1. Mismatch between bid/ask values and agent utilities.")
            print(f"  2. Overestimated initial utilities.")
            print(f"  3. High frictions or spread preventing trades.")

    def get_order_book(self):
        return self.order_book

    def get_trade_history(self):
        return self.trade_history

def run_market_simulation(num_buyers: int, num_sellers: int, num_units: int, buyer_base_value: int, seller_base_value: int, spread: float, max_rounds: int):
    # Generate test agents
    agents = generate_llm_market_agents(num_agents=num_buyers + num_sellers, num_units=num_units, buyer_base_value=buyer_base_value, seller_base_value=seller_base_value, spread=spread)
    
    # Create the environment
    env = Environment(agents=agents)

    # Print initial market state
    env.print_market_state()

    # Calculate and print initial utilities
    print("\nInitial Utilities:")
    for agent in env.agents:
        initial_utility = env.get_agent_utility(agent)
        print(f"Agent {agent.zi_agent.id} ({'Buyer' if agent.preference_schedule.is_buyer else 'Seller'}): {initial_utility:.2f}")

    # Run the auction
    auction = DoubleAuction(environment=env, max_rounds=max_rounds)
    auction.run_auction()

    # Analyze the auction results and plot
    analyze_and_plot_auction_results(auction, env)

if __name__ == "__main__":
    # Generate test agents
    num_buyers = 5
    num_sellers = 5
    spread = 0.5

    llm_config= {
        "client": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.5,
        "response_format": {
            "type": "json_object"
        }
    }
    agents = generate_llm_market_agents(
        num_agents=num_buyers + num_sellers, 
        num_units=5, 
        buyer_base_value=100, 
        seller_base_value=80, 
        spread=spread, 
        use_llm=True,
        llm_config=llm_config)
    
    # Create the environment
    env = Environment(agents=agents)

    # Print initial market state
    env.print_market_state()

    # Calculate and print initial utilities
    print("\nInitial Utilities:")
    for agent in env.agents:
        initial_utility = env.get_agent_utility(agent)
        print(f"Agent {agent.zi_agent.id} ({'Buyer' if agent.zi_agent.preference_schedule.is_buyer else 'Seller'}): {initial_utility:.2f}")

    # Run the auction
    auction = DoubleAuction(environment=env, max_rounds=5)
    auction.run_auction()

    # Analyze and plot results
    analyze_and_plot_auction_results(auction, env)