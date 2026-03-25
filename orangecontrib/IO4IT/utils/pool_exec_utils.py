# pool_exec_utils.py
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Optional, Tuple

def available_cpus(default: int = 4) -> int:
    c = os.cpu_count()
    return c if (c and c > 0) else default

def cpu_label_text() -> str:
    return f"🖥️ CPU dispo : {available_cpus()}"

def shutdown_executor(executor: Optional[ProcessPoolExecutor]) -> None:
    if executor is not None:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)
        except Exception:
            pass

def create_or_update_executor(
    executor: Optional[ProcessPoolExecutor],
    current_workers: Optional[int],
    new_workers: int,
) -> Tuple[ProcessPoolExecutor, int, str, bool]:
    changed = (executor is None) or (current_workers != int(new_workers))
    if changed:
        shutdown_executor(executor)
        executor = ProcessPoolExecutor(max_workers=int(new_workers))
        return executor, int(new_workers), f"Executor prêt ({int(new_workers)} workers).", True
    else:
        return executor, int(current_workers), f"Executor inchangé ({int(new_workers)} workers).", False
