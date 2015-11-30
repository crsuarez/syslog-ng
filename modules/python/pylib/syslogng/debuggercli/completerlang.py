from __future__ import print_function, absolute_import
import sys
from abc import abstractmethod, ABCMeta
import ply.yacc as yacc
from .tablexer import TabLexer


class CompleterLang(object):
    """Class encapsulating a language (or grammar) used by tab completion

    Derived classes should define their ply.yacc rules in their body, which is
    then translated at instantiation time.
    """
    __metaclass__ = ABCMeta

    def __init__(self):
        self._initialize_rules()
        self._parser = yacc.yacc(module=self, write_tables=False, debug=False, errorlog=yacc.NullLogger())
        self._lexer = TabLexer(self._construct_lexer())
        self._expected_tokens = []
        self._token_position = -1

    @abstractmethod
    def _construct_lexer(self):
        raise NotImplementedError

    def _initialize_rules(self):
        pass

    def get_expected_tokens(self, text, drop_last_token):
        self._lexer.set_drop_last_token(drop_last_token)
        self._parser.parse(text, lexer=self._lexer)
        return self._expected_tokens, self._lexer.get_replaced_token(), self._token_position

    def p_error(self, p):
        if p is None:
            # EOF
            return None
        elif p.type == 'TAB':
            # We look up the current grammar state from the local variables of the caller,
            # as it doesn't publish this information in self.
            #
            # This is somewhat fragile, however I don't really expect this variable to change
            # too frequently.
            #
            # I don't want to hide this call within the _handle_injected_tab_token() call, as
            # this is the very function that is close enough to the caller, moving this information
            # deeper would probably improve readability at the cost of increasing fragility.

            # pylint: disable=protected-access
            if 'state' in sys._getframe(1).f_locals:
                parser_state = sys._getframe(1).f_locals['state']
            elif 'state' in sys._getframe(2).f_locals:
                parser_state = sys._getframe(2).f_locals['state']
            else:
                return None

            # now handle the error that the TAB token caused
            self._token_position = p.lexpos
            self._collect_expected_tokens_and_productions(parser_state)
            self._parser.errok()

    def _collect_expected_tokens_and_productions(self, parser_state):
        self._expected_tokens = []
        self._collect_expected_tokens_for_a_given_state(parser_state)

    def _collect_expected_tokens_for_a_given_state(self, state):
        for token, next_state in self._iter_parser_actions(state):
            if token != '$end':
                self._expected_tokens.append(token)

            next_state = self._shift_production_if_needed(next_state, token)

            # negative next_state value means one of two things:
            #
            #    1) there's a syntax error and the current token does not match
            #       the rule we are evaluating right now
            #
            #    2) this token would trigger another rule shift, which we don't
            #       support right now.
            #

            if next_state >= 0:
                self._collect_expected_productions(next_state)

    def _collect_expected_productions(self, state):
        for _, next_state in self._iter_parser_actions(state):
            if next_state < 0:
                # production shift, we care about production shifts which would translate the
                # next_state token
                production = self._lookup_production(next_state)
                if production.len and production.name not in self._expected_tokens:
                    self._expected_tokens.append(production.name)

    def _iter_parser_actions(self, parser_state):
        return self._parser.action[parser_state].items()

    @staticmethod
    def _are_we_shifting_a_production(state):
        return state < 0

    def _shift_production(self, production, token):
        translated_state = self._get_target_state_after_shifting_production(production)
        try:
            # this might be negative (e.g. indicate a production shift).
            return self._parser.action[self._parser.goto[translated_state][production.name]][token]
        except KeyError:
            # this indicates a syntax error, the current token
            # does not match any rules where this production
            # is referenced from
            return -1

    def _shift_production_if_needed(self, state, token):
        if self._are_we_shifting_a_production(state):
            production = self._lookup_production(state)
            return self._shift_production(production, token)
        else:
            return state

    def _lookup_production(self, state):
        return self._parser.productions[-state]

    def _get_target_state_after_shifting_production(self, production):
        return self._parser.statestack[-production.len - 1]
