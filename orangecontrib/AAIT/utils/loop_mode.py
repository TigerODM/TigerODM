"""
Loop modes shared by Loop Start (OWStartLoop) and End Loop (OWEndLoop).

Backward compatibility
----------------------
Before this module existed, the mode was stored in two string settings of
Loop Start:
    str_iterate_still_nb_line_dont_change  ("True"/"False")
    str_iter_of_line_number                ("True"/"False")
`from_legacy` converts them to a mode with exactly the priority the old code
used (the "row count is stable" flag was tested first), and `to_legacy` keeps
them written so older versions of the add-on can still open new workflows.
"""


class LoopMode:
    UNSET = -1  # setting not saved yet -> derive it from the legacy settings

    WHOLE_UNTIL_ITER = 0            # legacy default (no checkbox)
    WHOLE_UNTIL_STABLE = 1          # legacy "checkBox"
    ROWS_SINGLE_PASS = 2            # legacy "checkBox_2"
    ROWS_STOP_ON_NEGATIVE_ITER = 3  # new

    ALL = (WHOLE_UNTIL_ITER, WHOLE_UNTIL_STABLE,
           ROWS_SINGLE_PASS, ROWS_STOP_ON_NEGATIVE_ITER)

    LABELS = {
        WHOLE_UNTIL_ITER: "Whole table - repeat while iter > 0 (default)",
        WHOLE_UNTIL_STABLE: "Whole table - repeat until the row count is stable",
        ROWS_SINGLE_PASS: "Row by row - process every row",
        ROWS_STOP_ON_NEGATIVE_ITER: "Row by row - stop everything when iter < 0",
    }

    DESCRIPTIONS = {
        WHOLE_UNTIL_ITER: (
            "The whole table goes through the loop at each round. Inside the loop, "
            "set the continuous column 'iter' to a value <= 0 on the rows that are "
            "done (it is added with the value 1 if missing). The loop stops when "
            "every row has iter <= 0. Rows and columns must not change, and each "
            "round must modify the table."
        ),
        WHOLE_UNTIL_STABLE: (
            "The whole table goes through the loop at each round. The loop stops "
            "as soon as a round returns the same number of rows it received. "
            "The 'iter' column is ignored."
        ),
        ROWS_SINGLE_PASS: (
            "Rows are sent into the loop one at a time and the results are "
            "concatenated. The loop stops after the last row. "
            "The 'iter' column is ignored."
        ),
        ROWS_STOP_ON_NEGATIVE_ITER: (
            "Rows are sent into the loop one at a time and the results are "
            "concatenated. If a row comes back with iter < 0, the whole loop stops: "
            "the remaining rows are skipped and the results so far (including that row) are sent. "
            "'iter' is optional and NOT added automatically: create it inside the "
            "loop (e.g. with a Formula)."
        ),
    }

    @staticmethod
    def from_legacy(str_iterate_still_nb_line_dont_change, str_iter_of_line_number):
        if str_iterate_still_nb_line_dont_change == "True":
            return LoopMode.WHOLE_UNTIL_STABLE
        if str_iter_of_line_number == "True":
            return LoopMode.ROWS_SINGLE_PASS
        return LoopMode.WHOLE_UNTIL_ITER

    @staticmethod
    def to_legacy(mode):
        """Return (str_iterate_still_nb_line_dont_change, str_iter_of_line_number).
        The new row-by-row mode degrades to "process every row" in older versions."""
        return ("True" if mode == LoopMode.WHOLE_UNTIL_STABLE else "False",
                "True" if LoopMode.is_row_by_row(mode) else "False")

    @staticmethod
    def is_row_by_row(mode):
        return mode in (LoopMode.ROWS_SINGLE_PASS, LoopMode.ROWS_STOP_ON_NEGATIVE_ITER)
