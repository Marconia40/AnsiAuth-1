from __future__ import annotations

from typing import Any


def debe_revertir_escalar(puesta: Any, previa: Any, ahora: Any) -> bool:
    return ahora == puesta and puesta != previa


class RollbackPorPlan:
    def _ejecutar_rollback_con_plan(self, device: Any, planificar) -> "tuple[bool, Any]":
        try:
            try:
                actual_ahora = self.reconciliar(device).get("actual")  # type: ignore[attr-defined]
            except Exception:
                actual_ahora = None
            pasos, verificar = planificar(actual_ahora)
            if not pasos:
                return False, None
            for op_key, variant, vars in pasos:
                resultado = device.driver.aplicar_paso(op_key, variant, vars, device, device.password)
                if resultado.get("rc", 1) != 0:
                    return True, False
        except Exception:
            return True, False

        if verificar is None:
            return True, True
        try:
            return True, bool(verificar(self.reconciliar(device).get("actual")))  # type: ignore[attr-defined]
        except Exception:
            return True, False
