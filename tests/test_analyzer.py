import textwrap
import unittest

from pin_audit import analyze


class PinTests(unittest.TestCase):
    def report(self, source, **kwargs):
        return analyze(textwrap.dedent(source), **kwargs)

    def test_hackpad_regression(self):
        report = self.report('''
            import board, busio, keypad
            display = busio.I2C(board.D5, board.D4)
            keys = keypad.KeyMatrix(row_pins=(board.D0, board.D1), column_pins=(board.D2, board.D3, board.D4, board.D5))
        ''')
        self.assertEqual({d.pin for d in report.conflicts}, {"D4", "D5"})
        self.assertEqual({d.related_line for d in report.conflicts}, {3})
        self.assertEqual(report.allocations, 2)

    def test_distinct_pins(self):
        self.assertEqual(self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D0)
            b = digitalio.DigitalInOut(board.D1)
        ''').diagnostics, [])

    def test_duplicate_within_matrix(self):
        report = self.report('''
            import board, keypad
            matrix = keypad.KeyMatrix((board.D0,), (board.D0,))
        ''')
        self.assertEqual([d.code for d in report.conflicts], ["PA002"])

    def test_direct_and_aliased_imports(self):
        report = self.report('''
            from board import D0 as BUTTON
            from digitalio import DigitalInOut as IO
            import board as pins
            import pwmio as pwm
            a = IO(BUTTON)
            b = pwm.PWMOut(pins.D0)
        ''')
        self.assertEqual(len(report.conflicts), 1)

    def test_reassignment_and_import_shadowing(self):
        report = self.report('''
            import board, digitalio
            p = board.D0
            p = board.D1
            a = digitalio.DigitalInOut(p)
            b = digitalio.DigitalInOut(board.D0)
            digitalio = object()
            c = digitalio.DigitalInOut(board.D1)
        ''')
        self.assertFalse(report.conflicts)
        self.assertTrue(report.incomplete)

    def test_explicit_deinit_and_handle_alias(self):
        report = self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D0)
            alias = a
            alias.deinit()
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(report.diagnostics, [])

    def test_rebinding_does_not_release_old_resource(self):
        report = self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D0)
            a = None
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(len(report.conflicts), 1)

    def test_context_lifetime(self):
        report = self.report('''
            import board, digitalio
            with digitalio.DigitalInOut(board.D0) as a:
                b = digitalio.DigitalInOut(board.D0)
                b.deinit()
            c = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(report.conflicts[0].line, 4)

    def test_with_existing_handle(self):
        report = self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D0)
            with a:
                pass
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(report.diagnostics, [])

    def test_branches_are_exclusive(self):
        report = self.report('''
            import board, digitalio
            if mode:
                a = digitalio.DigitalInOut(board.D0)
            else:
                a = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(report.diagnostics, [])

    def test_branch_live_resource_after_join(self):
        report = self.report('''
            import board, digitalio
            if mode:
                a = digitalio.DigitalInOut(board.D0)
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(len(report.conflicts), 1)

    def test_released_in_every_branch(self):
        report = self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D0)
            if mode:
                a.deinit()
            else:
                a.deinit()
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(report.diagnostics, [])

    def test_constant_branch_is_pruned(self):
        report = self.report('''
            import board, digitalio
            if False:
                a = digitalio.DigitalInOut(board.D0)
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertEqual(report.allocations, 1)
        self.assertFalse(report.conflicts)

    def test_raise_ends_branch(self):
        report = self.report('''
            import board, digitalio
            if mode:
                a = digitalio.DigitalInOut(board.D0)
                raise RuntimeError()
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertFalse(report.conflicts)

    def test_shared_bus_is_not_a_second_allocation(self):
        report = self.report('''
            import board, busio
            i2c = busio.I2C(board.SCL, board.SDA)
            sensor = Driver(i2c, address=0x40)
            display = OtherDriver(i2c, address=0x3c)
        ''')
        self.assertEqual(report.diagnostics, [])
        self.assertEqual(report.allocations, 1)

    def test_alias_groups_are_explicit_and_transitive(self):
        source = '''
            import board, digitalio
            a = digitalio.DigitalInOut(board.SDA)
            b = digitalio.DigitalInOut(board.GP4)
        '''
        self.assertFalse(self.report(source).conflicts)
        report = self.report(source, aliases=[["D4", "SDA"], ["GP4", "D4"]])
        self.assertEqual(len(report.conflicts), 1)

    def test_redundant_and_cyclic_alias_groups_do_not_loop(self):
        report = self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D4)
            b = digitalio.DigitalInOut(board.SDA)
        ''', aliases=[["D4", "SDA"], ["SDA", "D4"], ["D4", "D4"]])
        self.assertEqual(len(report.conflicts), 1)

    def test_assert_allocation_is_reported_as_skipped(self):
        report = self.report('''
            import board, digitalio
            assert digitalio.DigitalInOut(board.D0)
        ''')
        self.assertTrue(report.incomplete)
        self.assertEqual(report.allocations, 0)

    def test_uart_optional_flow_control_pins(self):
        report = self.report('''
            import board, busio, digitalio
            serial = busio.UART(tx=None, rx=board.D1, rts=board.D2)
            a = digitalio.DigitalInOut(board.D2)
        ''')
        self.assertEqual(len(report.conflicts), 1)
        self.assertFalse(report.incomplete)

    def test_non_pin_positional_argument(self):
        report = self.report('''
            import board, rotaryio
            encoder = rotaryio.IncrementalEncoder(board.D0, board.D1, 4)
        ''')
        self.assertEqual(report.diagnostics, [])

    def test_pin_tuple_aliases_concat_and_index(self):
        report = self.report('''
            import board, digitalio, keypad
            first, second = board.D0, board.D1
            pins = (first,) + (second,)
            keys = keypad.Keys(pins, value_when_pressed=False)
            a = digitalio.DigitalInOut(pins[1])
        ''')
        self.assertEqual([d.pin for d in report.conflicts], ["D1"])

    def test_unknown_pin_is_coverage_gap(self):
        report = self.report('''
            import digitalio
            a = digitalio.DigitalInOut(choose_pin())
        ''')
        self.assertTrue(report.incomplete)
        self.assertFalse(report.conflicts)

    def test_board_default_bus_is_coverage_gap(self):
        report = self.report('''
            import board
            bus = board.I2C()
        ''')
        self.assertTrue(report.incomplete)

    def test_function_not_treated_as_executed(self):
        report = self.report('''
            import board, digitalio
            def allocate():
                a = digitalio.DigitalInOut(board.D0)
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertTrue(report.incomplete)
        self.assertFalse(report.conflicts)
        self.assertEqual(report.allocations, 1)

    def test_loop_allocations_are_not_unrolled(self):
        report = self.report('''
            import board, digitalio
            for p in (board.D0, board.D1):
                a = digitalio.DigitalInOut(p)
        ''')
        self.assertTrue(report.incomplete)
        self.assertEqual(report.allocations, 0)

    def test_non_hardware_loop_does_not_add_noise(self):
        report = self.report('''
            while True:
                print("hello")
        ''')
        self.assertEqual(report.diagnostics, [])

    def test_wildcard_import(self):
        self.assertTrue(self.report('from board import *').incomplete)

    def test_syntax_error(self):
        report = self.report('if (')
        self.assertTrue(report.failed)
        self.assertEqual(report.diagnostics[0].code, "PA900")

    def test_path_budget_is_not_a_clean_result(self):
        source = '\n'.join(f'if flag{i}:\n    pass' for i in range(7))
        self.assertTrue(self.report(source, max_paths=8).failed)

    def test_firmware_is_never_executed(self):
        report = self.report('raise RuntimeError("must never execute")')
        self.assertFalse(report.failed)

    def test_starred_arguments_are_not_guessed(self):
        report = self.report('''
            import board, busio
            pins = (board.D0, board.D1)
            bus = busio.I2C(*pins)
        ''')
        self.assertTrue(report.incomplete)

    def test_sequence_mutation_invalidates_resolution(self):
        report = self.report('''
            import board, keypad
            pins = [board.D0]
            pins.append(board.D1)
            keys = keypad.Keys(pins, value_when_pressed=False)
        ''')
        self.assertTrue(report.incomplete)
        self.assertTrue(any(d.code == "PA100" for d in report.diagnostics))

    def test_mutation_also_invalidates_sequence_alias(self):
        report = self.report('''
            import board, keypad
            pins = [board.D0]
            alias = pins
            alias.append(board.D1)
            keys = keypad.Keys(pins, value_when_pressed=False)
        ''')
        self.assertTrue(any(d.code == "PA100" for d in report.diagnostics))

    def test_imports_inside_function_are_coverage_gap(self):
        report = self.report('''
            def setup():
                import board, digitalio
                return digitalio.DigitalInOut(board.D0)
        ''')
        self.assertTrue(report.incomplete)
        self.assertEqual(report.allocations, 0)

    def test_non_ascii_columns_are_character_positions(self):
        source = 'import board, digitalio\né = digitalio.DigitalInOut(board.D0)\nβ = digitalio.DigitalInOut(board.D0)'
        report = self.report(source)
        self.assertEqual(report.conflicts[0].column, 5)
        self.assertEqual(report.conflicts[0].related_column, 5)

    def test_allocation_in_conditional_expression_is_not_unconditional(self):
        report = self.report('''
            import board, digitalio
            a = digitalio.DigitalInOut(board.D0) if flag else None
            b = digitalio.DigitalInOut(board.D0)
        ''')
        self.assertTrue(report.incomplete)
        self.assertFalse(report.conflicts)

    def test_multiple_pins_in_unknown_argument_do_not_hide_known_conflict(self):
        report = self.report('''
            import board, busio, digitalio
            a = digitalio.DigitalInOut(board.D0)
            bus = busio.I2C(scl=choose_pin(), sda=board.D0)
        ''')
        self.assertTrue(report.incomplete)
        self.assertEqual(len(report.conflicts), 1)


if __name__ == "__main__":
    unittest.main()
