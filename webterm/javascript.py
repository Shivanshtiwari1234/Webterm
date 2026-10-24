from __future__ import annotations

import multiprocessing as mp
import time
from multiprocessing.connection import Connection


def _javascript_worker(
    conn: Connection,
    memory_limit_mb: int,
) -> None:
    """Execute JavaScript inside an isolated worker process."""
    try:
        import quickjs

        context = quickjs.Context()
        context.set_memory_limit(memory_limit_mb * 1024 * 1024)

        def log(level: str, message: str) -> None:
            try:
                conn.send(("log", level, message))
            except (BrokenPipeError, EOFError, OSError):
                pass

        context.add_callable(
            "__webterm_log",
            lambda message: log("log", message),
        )
        context.add_callable(
            "__webterm_warn",
            lambda message: log("warn", message),
        )
        context.add_callable(
            "__webterm_error",
            lambda message: log("error", message),
        )

        context.eval("""
            globalThis.console = {
                log: (...args) =>
                    __webterm_log(args.map(String).join(" ")),
                info: (...args) =>
                    __webterm_log(args.map(String).join(" ")),
                warn: (...args) =>
                    __webterm_warn(args.map(String).join(" ")),
                error: (...args) =>
                    __webterm_error(args.map(String).join(" "))
            };
        """)

        conn.send(("ready", None))

        while True:
            try:
                message = conn.recv()
            except (EOFError, OSError):
                break

            command = message[0]

            if command == "close":
                break

            if command != "execute":
                continue

            source = message[1]

            try:
                result = context.eval(source)
                result = None if result is None else str(result)
                conn.send(("result", result))
            except Exception as exc:
                conn.send(("error", str(exc)))

            conn.send(("done", None))

    except BaseException as exc:
        try:
            conn.send(("fatal", str(exc)))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        conn.close()


class JavaScriptRuntime:
    """A persistent JavaScript worker dedicated to one browser tab."""

    def __init__(
        self,
        timeout: float = 2.0,
        memory_limit_mb: int = 32,
        startup_timeout: float = 10.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if memory_limit_mb < 8:
            raise ValueError("memory_limit_mb must be at least 8")
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be greater than zero")

        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self.startup_timeout = startup_timeout

        self.console_messages: list[str] = []
        self._closed = False

        self._ctx = mp.get_context("spawn")
        self._parent: Connection | None = None
        self._process: mp.Process | None = None

        self._start_worker()

    def _start_worker(self) -> None:
        """Start a fresh JavaScript worker and wait for initialization."""
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")

        parent, child = self._ctx.Pipe(duplex=True)

        process = self._ctx.Process(
            target=_javascript_worker,
            args=(child, self.memory_limit_mb),
            name="Webterm-JavaScript",
            daemon=True,
        )

        try:
            process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        finally:
            child.close()

        self._parent = parent
        self._process = process

        deadline = time.monotonic() + self.startup_timeout

        while time.monotonic() < deadline:
            if parent.poll(0.05):
                try:
                    message = parent.recv()
                except (EOFError, OSError):
                    break

                kind, *values = message

                if kind == "ready":
                    return

                if kind == "fatal":
                    error = values[0] if values else "Unknown worker error"
                    self._stop_worker()
                    raise RuntimeError(
                        f"JavaScript worker failed to initialize: {error}"
                    )

            if not process.is_alive():
                break

        self._stop_worker()
        raise RuntimeError("JavaScript worker failed to start")

    def _stop_worker(self) -> None:
        """Terminate and clean up the current worker process."""
        process = self._process
        parent = self._parent

        self._process = None
        self._parent = None

        if parent is not None:
            try:
                parent.close()
            except OSError:
                pass

        if process is None:
            return

        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)

            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        finally:
            if not process.is_alive():
                process.close()

    def _ensure_worker(self) -> bool:
        """Ensure a live worker exists; restart it if needed."""
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")

        if self._process is not None and self._process.is_alive():
            return True

        self._stop_worker()

        try:
            self._start_worker()
            return True
        except (OSError, RuntimeError) as exc:
            self.console_messages.append(
                f"[JavaScript worker error] Could not start worker: {exc}"
            )
            return False

    def execute(self, source: str) -> str | None:
        """Execute JavaScript and return the result, if any."""
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")

        if not isinstance(source, str):
            raise TypeError("source must be a string")

        if not self._ensure_worker():
            return None

        assert self._parent is not None
        assert self._process is not None

        try:
            self._parent.send(("execute", source))
        except (BrokenPipeError, EOFError, OSError) as exc:
            self.console_messages.append(
                f"[JavaScript worker error] Communication failed: {exc}"
            )
            self._stop_worker()
            return None

        deadline = time.monotonic() + self.timeout
        result: str | None = None

        while time.monotonic() < deadline:
            if self._parent.poll(0.05):
                try:
                    message = self._parent.recv()
                except (EOFError, OSError):
                    break

                kind, *values = message

                if kind == "log":
                    level, text = values
                    prefix = "" if level == "log" else f"[{level}] "
                    self.console_messages.append(prefix + text)

                elif kind == "result":
                    result = values[0]

                elif kind == "error":
                    self.console_messages.append(f"[JavaScript error] {values[0]}")

                elif kind == "fatal":
                    self.console_messages.append(
                        f"[JavaScript worker error] {values[0]}"
                    )
                    break

                elif kind == "done":
                    return result

            if not self._process.is_alive():
                break

        self._stop_worker()
        self.console_messages.append(
            f"[JavaScript error] Execution exceeded the "
            f"{self.timeout:g}-second timeout or the worker exited. "
            "The worker will restart on the next execution."
        )
        return None

    def close(self) -> None:
        """Ask the worker to exit cleanly, then force-stop if it does not."""
        if self._closed:
            return
        self._closed = True
        process = self._process
        parent = self._parent
        if parent is not None and process is not None and process.is_alive():
            try:
                parent.send(("close", None))
            except (BrokenPipeError, EOFError, OSError):
                pass
            process.join(timeout=0.5)
        self._stop_worker()

    def __enter__(self) -> JavaScriptRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
