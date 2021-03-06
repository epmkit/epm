from ply import lex, yacc


class Lex(object):
    tokens = ('STRING', 'QSTRING', 'SQSTRING',
              'EQ', 'NEQ', 'LT', 'LE', 'GT', 'GE',
              'AND', 'OR',
   )

    # Regular expression rules for simple tokens
    t_STRING = r'[\w\.\-]+'
    t_QSTRING = r'\"[\w\.\- ]+\"'
    t_SQSTRING = r"'[\w\.\- ]+'"
    t_AND = r'&&'
    t_OR = r'\|\|'

    t_EQ = r'=='
    t_NEQ = r'!='
    t_LT = r'<'
    t_LE = r'<='
    t_GT = r'>'
    t_GE = r'>='

    # Define a rule so we can track line numbers
    def t_newline(self, t):
        r'\n+'
        t.lexer.lineno += len(t.value)

    # A string containing ignored characters (spaces and tabs)
    t_ignore = ' \t'

    # Error handling rule
    def t_error(self, t):
        print("Illegal character '%s'" % t.value[0])
        t.lexer.skip(1)


class Yacc(Lex):

    @staticmethod
    def p_logical_operation(p):
        '''operation : expression
                     | expression AND expression
                     | expression OR expression
        '''
        if len(p) == 2:
            p[0] = p[1]
        elif p[2] == '&&':
            p[0] = p[1] and p[3]
        elif p[2] == '||':
            p[0] = p[1] or p[3]

    def p_string(self, p):
        '''string : STRING
                  | QSTRING
                  | SQSTRING
        '''
        if p[1][0] in ["'", '"']:
            p[0] = p[1][1:-1].strip()
        else:
            p[0] = p[1]

    def p_expression(self, p):
        '''expression : string EQ string
                      | string NEQ string
                      | string LT string
                      | string LE string
                      | string GT string
                      | string GE string
                      | string
        '''
        op = None
        value = self._vars.get(p[1], None)
        if len(p) > 2:
            op = p[2]
            value = str(self._vars.get(p[1], self._None))

        if op == '==':
            p[0] = value == p[3]
        elif op == '!=':
            p[0] = value != p[3]
        elif op == '>':
            p[0] = value > p[3]
        elif op == '>=':
            p[0] = value >= p[3]
        elif op == '<':
            p[0] = value < p[3]
        elif op == '<=':
            p[0] = value <= p[3]
        elif op is None:
            p[0] = bool(value)

    # Error rule for syntax errors
    def p_error(self, p):
        raise SyntaxError('expr error: %s' % self._expr)

    def __init__(self, vars, none='None', debug=False):
        # Build the parser
        self._expr = None
        self._vars = vars or dict()
        self._None = none
        self._lexer = lex.lex(module=self)
        self._parser = yacc.yacc(module=self, write_tables=debug, debug=debug)

    def parse(self, expr):
        self._expr = expr
        return self._parser.parse(expr)

