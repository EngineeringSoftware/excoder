#!/usr/bin/env python3

from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on_prompt_gen import AddOnPrompt


class AddOnRepairPrompt(AddOnPrompt):
    def _get_multi_ebt_args(
        self, data: tuple[DataMultiEBT, str, dict[str, Any], dict[str, Any] | None]
    ) -> dict[str, str]:  # type: ignore
        multi_ebt_data, tent_code, ebt_eval_out, nebt_eval_out = data
        out = super()._get_multi_ebt_args(multi_ebt_data)

        # Compose err cor_info field
        error_info = self._compose_error_info(
            multi_ebt_data, ebt_eval_out, nebt_eval_out
        )
        out["error_info"] = error_info
        out["tent_code"] = tent_code

        return out

    def _compose_error_info(
        self,
        multi_ebt_data: DataMultiEBT,
        ebt_eval_out: dict[str, Any],
        nebt_eval_out: dict[str, Any] | None,
    ) -> str:
        """Compose error information from eval output.

        If module result failed, return stdout content.
        For EBT tests: if failed, write "Test #{num} failed" and error message.
        For NEBT tests: if failed, find corresponding NEBT from multi_ebt_data.nebt[test_idx] and add to prompt.
        """
        error_parts = []

        # Check if module compilation/build failed (from EBT eval)
        module_result = ebt_eval_out["module_result"]
        if not module_result["success"]:
            error_parts.append(
                "Compilation of maven module failed:\n" + module_result["stdout"]
            )

        # Check for failed EBT tests
        ebt_each_test = ebt_eval_out["each_test"]
        for i, test in enumerate(ebt_each_test):
            if not test["passed"]:
                error_parts.append(f"EBT #{i} (shown above) failed:\n{test['stdout']}")

        # Check for failed NEBT tests (if available)
        if nebt_eval_out is not None:
            nebt_each_test = nebt_eval_out["each_test"]
            for test_idx, test in enumerate(nebt_each_test):
                if not test["passed"] and test_idx < len(multi_ebt_data.nebts):
                    nebt_code = multi_ebt_data.nebts[test_idx].raw_code
                    error_parts.append(
                        f"Non-EBT Test #{test_idx} failed:\n"
                        f"Code:\n{nebt_code}\n\n"
                        f"Error:\n{test['stdout']}"
                    )
        return "\n\n".join(error_parts) if error_parts else "No errors found"
