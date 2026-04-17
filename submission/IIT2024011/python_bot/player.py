import eval7
import random
from skeleton.actions import FoldAction, CallAction, CheckAction, RaiseAction
from skeleton.states import GameState, TerminalState, RoundState
from skeleton.bot import Bot
from skeleton.runner import parse_args, run_bot

class Player(Bot):
    def handle_new_round(self, game_state, round_state, active):
        pass

    def handle_round_over(self, game_state, terminal_state, active):
        pass

    def get_action(self, game_state, round_state, active):
        legal_actions = round_state.legal_actions()
        street = round_state.street  
        
        my_cards_str = round_state.hands[active]
        board_cards_str = round_state.deck

        # -----------------------------------------------------------
        # CORE GAME STATE MATH
        # -----------------------------------------------------------
        my_stack = round_state.stacks[active]
        opp_stack = round_state.stacks[1-active]
        pot = (400 - my_stack) + (400 - opp_stack)
        continue_cost = round_state.pips[1-active] - round_state.pips[active]

        # Bounty Protection (Free EV)
        my_bounty_rank = round_state.bounties[active]
        bounty_hit = False
        if my_bounty_rank != '-1':
            all_visible = my_cards_str + board_cards_str
            if any(card[0] == my_bounty_rank for card in all_visible):
                bounty_hit = True

        # -----------------------------------------------------------
        # PRE-FLOP STRATEGY (Mixed Strategy TAG)
        # -----------------------------------------------------------
        if street == 0:
            rank_map = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
            r1, r2 = rank_map[my_cards_str[0][0]], rank_map[my_cards_str[1][0]]
            high_card, low_card = max(r1, r2), min(r1, r2)
            
            is_premium = (r1 == r2) or (low_card >= 10) or (high_card == 14 and low_card >= 8)

            if is_premium or bounty_hit:
                # RANDOMIZATION: Trap with premium hands 20% of the time
                if RaiseAction in legal_actions and random.random() < 0.8:
                    min_raise, max_raise = round_state.raise_bounds()
                    return RaiseAction(min(max_raise, min_raise + int(pot * 0.5)))
                if CallAction in legal_actions:
                    return CallAction()
                return CheckAction()
            else:
                # RANDOMIZATION: Execute a crazy pre-flop bluff 5% of the time to remain unreadable
                if RaiseAction in legal_actions and random.random() < 0.05:
                    min_raise, max_raise = round_state.raise_bounds()
                    return RaiseAction(min_raise)
                if CheckAction in legal_actions:
                    return CheckAction()
                return FoldAction()

        # -----------------------------------------------------------
        # POST-FLOP STRATEGY (Pot Odds & MDF)
        # -----------------------------------------------------------
        else:
            my_eval7_cards = [eval7.Card(c) for c in my_cards_str]
            board_eval7_cards = [eval7.Card(c) for c in board_cards_str]
            
            # eval7 returns a hand value up to 7462. Normalize it to a 0.0 - 1.0 percentile.
            hand_value = eval7.evaluate(my_eval7_cards + board_eval7_cards)
            strength_percentile = hand_value / 7462.0

            # SCENARIO A: We are facing a bet
            if continue_cost > 0:
                # Math: Calculate exactly what equity we need to call profitably
                pot_odds = continue_cost / (pot + continue_cost)
                
                # Math: Minimum Defense Frequency (MDF) to stop auto-profit bluffs
                mdf = pot / (pot + continue_cost)

                if strength_percentile >= pot_odds or bounty_hit:
                    # Our hand is mathematically profitable to play.
                    # Mix in value raises 20% of the time so we aren't just a calling station.
                    if RaiseAction in legal_actions and random.random() < 0.2:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min(max_raise, min_raise + int(pot * 0.5)))
                    if CallAction in legal_actions:
                        return CallAction()
                else:
                    # Our hand is weak, but if we fold 100% of our weak hands, we get exploited.
                    # Use MDF to randomly convert some weak hands into aggressive bluffs.
                    if RaiseAction in legal_actions and random.random() < (1.0 - mdf) * 0.15:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min_raise + int(pot * 0.25))
                    return FoldAction()

            # SCENARIO B: We are first to act, or opponent checked
            else:
                # Polarized Betting Range: Bet our best hands, and bluff our worst hands.
                if strength_percentile > 0.75:
                    if RaiseAction in legal_actions:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min(max_raise, min_raise + int(pot * 0.75)))
                
                elif strength_percentile < 0.3:
                    # We have nothing. Bluff 25% of the time based on optimal bet sizing.
                    if RaiseAction in legal_actions and random.random() < 0.25:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min(max_raise, min_raise + int(pot * 0.5)))
                
                if CheckAction in legal_actions:
                    return CheckAction()
                return FoldAction()

if __name__ == '__main__':
    run_bot(Player(), parse_args())