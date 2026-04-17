import eval7
import random
from skeleton.actions import FoldAction, CallAction, CheckAction, RaiseAction
from skeleton.states import GameState, TerminalState, RoundState
from skeleton.bot import Bot
from skeleton.runner import parse_args, run_bot


def estimate_equity(hole_cards, board_cards, num_simulations=500):
    """
    Monte Carlo equity estimation.
    Returns a float in [0.0, 1.0] representing win probability vs a random opponent hand.
    """
    deck = eval7.Deck()
    known = set(hole_cards + board_cards)
    deck.cards = [c for c in deck.cards if c not in known]

    wins = 0
    ties = 0
    for _ in range(num_simulations):
        deck.shuffle()
        remaining_board = 5 - len(board_cards)
        opp_hole = deck.cards[:2]
        runout = deck.cards[2: 2 + remaining_board]
        full_board = board_cards + runout

        my_score = eval7.evaluate(hole_cards + full_board)
        opp_score = eval7.evaluate(opp_hole + full_board)

        if my_score > opp_score:
            wins += 1
        elif my_score == opp_score:
            ties += 1

    return (wins + 0.5 * ties) / num_simulations


class Player(Bot):
    def handle_new_round(self, game_state, round_state, active):
        pass

    def handle_round_over(self, game_state, terminal_state, active):
        pass

    def get_action(self, game_state, round_state, active):
        legal_actions = round_state.legal_actions()
        street = round_state.street

        my_cards_str = round_state.hands[active]
        board_cards_str = round_state.deck[:street] if street > 0 else []

        # -----------------------------------------------------------
        # CORE GAME STATE MATH
        # -----------------------------------------------------------
        my_stack = round_state.stacks[active]
        opp_stack = round_state.stacks[1 - active]
        pot = (400 - my_stack) + (400 - opp_stack)
        continue_cost = round_state.pips[1 - active] - round_state.pips[active]

        # Position: active == 0 is the dealer/button (acts last post-flop)
        in_position = (active == 0)

        # Stack-to-Pot Ratio
        spr = my_stack / max(pot, 1)

        # -----------------------------------------------------------
        # BOUNTY: Use as an equity bonus, not a blanket override
        # -----------------------------------------------------------
        my_bounty_rank = round_state.bounties[active]
        bounty_bonus = 0.0
        if my_bounty_rank != '-1':
            all_visible = my_cards_str + board_cards_str
            if any(card[0] == my_bounty_rank for card in all_visible):
                bounty_bonus = 0.15

        # -----------------------------------------------------------
        # PRE-FLOP STRATEGY (TAG with position awareness)
        # -----------------------------------------------------------
        if street == 0:
            rank_map = {
                '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
                '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14
            }
            r1, r2 = rank_map[my_cards_str[0][0]], rank_map[my_cards_str[1][0]]
            high_card, low_card = max(r1, r2), min(r1, r2)
            suited = my_cards_str[0][1] == my_cards_str[1][1]
            is_pair = (r1 == r2)

            is_premium = (
                is_pair or
                (low_card >= 10) or
                (high_card == 14 and low_card >= 8) or
                (suited and high_card >= 10) or                         # KTs, QTs, JTs
                (suited and high_card - low_card <= 4 and low_card >= 5) # suited connectors 56s+
            )

            # Wider opening range in position
            is_playable = in_position and (
                (suited and low_card >= 4) or
                (high_card >= 10 and low_card >= 6) or
                (is_pair)
            )

            if is_premium or bounty_bonus > 0:
                if RaiseAction in legal_actions and random.random() < 0.8:
                    min_raise, max_raise = round_state.raise_bounds()
                    return RaiseAction(min(max_raise, min_raise + int(pot * 0.5)))
                if CallAction in legal_actions:
                    return CallAction()
                return CheckAction()

            elif is_playable:
                # Playable hands: call or occasionally raise as a steal
                if RaiseAction in legal_actions and random.random() < 0.3:
                    min_raise, max_raise = round_state.raise_bounds()
                    return RaiseAction(min_raise)
                if CallAction in legal_actions:
                    return CallAction()
                return CheckAction()

            else:
                # Garbage hands: fold, but bluff-raise 5% to stay unpredictable
                if RaiseAction in legal_actions and random.random() < 0.05:
                    min_raise, max_raise = round_state.raise_bounds()
                    return RaiseAction(min_raise)
                if CheckAction in legal_actions:
                    return CheckAction()
                return FoldAction()

        # -----------------------------------------------------------
        # POST-FLOP STRATEGY (True Monte Carlo Equity)
        # -----------------------------------------------------------
        else:
            my_eval7_cards = [eval7.Card(c) for c in my_cards_str]
            board_eval7_cards = [eval7.Card(c) for c in board_cards_str]

            # True win probability via simulation
            raw_equity = estimate_equity(my_eval7_cards, board_eval7_cards)
            equity = min(raw_equity + bounty_bonus, 1.0)

            # Street-specific thresholds and bluff frequencies
            if street == 5:   # River: no more draws, polarize hard
                bluff_freq    = 0.15
                bet_threshold = 0.62
                value_raise_freq = 0.35
            elif street == 4: # Turn: semi-bluffs dry up
                bluff_freq    = 0.22
                bet_threshold = 0.68
                value_raise_freq = 0.25
            else:             # Flop: c-bets and semi-bluffs most common
                bluff_freq    = 0.30
                bet_threshold = 0.72
                value_raise_freq = 0.20

            # Position adjustment: bet/bluff more in position
            if in_position:
                bluff_freq    += 0.05
                bet_threshold -= 0.04

            # -----------------------------------------------------------
            # COMMITMENT CHECK: Low SPR → just shove with any decent equity
            # -----------------------------------------------------------
            if spr < 2 and equity > 0.35:
                if RaiseAction in legal_actions:
                    _, max_raise = round_state.raise_bounds()
                    return RaiseAction(max_raise)
                if CallAction in legal_actions:
                    return CallAction()

            # -----------------------------------------------------------
            # SCENARIO A: Facing a bet
            # -----------------------------------------------------------
            if continue_cost > 0:
                pot_odds = continue_cost / (pot + continue_cost)
                mdf      = pot / (pot + continue_cost)

                if equity >= pot_odds:
                    # Profitable to continue; occasionally raise for value
                    if RaiseAction in legal_actions and random.random() < value_raise_freq:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min(max_raise, min_raise + int(pot * 0.6)))
                    if CallAction in legal_actions:
                        return CallAction()
                    return CheckAction()
                else:
                    # Weak hand: defend MDF with a bluff-raise, otherwise fold
                    if RaiseAction in legal_actions and random.random() < (1.0 - mdf) * bluff_freq:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min(max_raise, min_raise + int(pot * 0.4)))
                    return FoldAction()

            # -----------------------------------------------------------
            # SCENARIO B: First to act, or facing a check
            # -----------------------------------------------------------
            else:
                if equity > bet_threshold:
                    # Value bet: size up with stronger hands
                    if RaiseAction in legal_actions:
                        min_raise, max_raise = round_state.raise_bounds()
                        bet_size = int(pot * (0.6 + (equity - bet_threshold) * 2.0))
                        return RaiseAction(min(max_raise, min_raise + bet_size))

                elif equity < 0.30:
                    # Bluff with our worst hands (polarized range)
                    if RaiseAction in legal_actions and random.random() < bluff_freq:
                        min_raise, max_raise = round_state.raise_bounds()
                        return RaiseAction(min(max_raise, min_raise + int(pot * 0.5)))

                # Middle hands: check/call line
                if CheckAction in legal_actions:
                    return CheckAction()
                return FoldAction()


if __name__ == '__main__':
    run_bot(Player(), parse_args())