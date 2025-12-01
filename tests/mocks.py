"""Lightweight stubs for Flask and requests used when optional deps are missing."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict


class FlaskType:
    def __init__(self, *a: Any, **kw: Any) -> None:
        self.routes: Dict[tuple[str, tuple[str, ...]], Any] = {}
        self.config: Dict[str, Any] = {}
        self._after_request_funcs = []
        self._before_request_funcs = []
        self._teardown_request_funcs = []

    def route(self, path: str, methods: list[str] | None = None):
        methods_tuple = tuple((methods or ["GET"]))

        def decorator(func):
            self.routes[(path, methods_tuple)] = func
            return func

        return decorator

    def after_request(self, func):
        self._after_request_funcs.append(func)
        return func

    def before_request(self, func):
        self._before_request_funcs.append(func)
        return func

    def teardown_request(self, func):
        self._teardown_request_funcs.append(func)
        return func

    def test_client(self):
        app = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, path, json=None):
                func = app.routes.get((path, ("POST",)))
                if not func:
                    raise AssertionError("Route not found")
                global request

                class Req:
                    is_json = True

                    def get_json(self, silent: bool = False):
                        return json

                request = Req()
                resp = func()
                status = 200
                data = resp
                if isinstance(resp, tuple):
                    data, status = resp

                class R:
                    def __init__(self, d, s):
                        self.status_code = s
                        self._d = d

                    def get_json(self):
                        return self._d

                    def get_data(self, as_text: bool = False):
                        return self._d if not as_text else str(self._d)

                return R(data, status)

            def get(self, path, query_string=None):
                func = app.routes.get((path, ("GET",)))
                if not func:
                    raise AssertionError("Route not found")
                global request

                class Req:
                    is_json = False
                    args = query_string or {}

                    def get_json(self, silent: bool = False):
                        return {}

                request = Req()
                resp = func()
                status = 200
                data = resp
                if isinstance(resp, tuple):
                    data, status = resp

                class R:
                    def __init__(self, d, s):
                        self.status_code = s
                        self._d = d

                    def get_json(self):
                        return self._d

                    def get_data(self, as_text: bool = False):
                        return self._d if not as_text else str(self._d)

                return R(data, status)

        return Client()

    def run(self, *a: Any, **k: Any) -> None:
        pass


class FlaskBlueprint:
    def __init__(self, *a: Any, **kw: Any) -> None:
        pass


def jsonify(obj: Any = None) -> Any:
    return obj


def send_from_directory(directory: os.PathLike[str] | str, path: os.PathLike[str] | str, **kwargs: Any) -> Any:
    return str(path)


class Request:
    def __init__(self) -> None:
        self.is_json = False
        self.environ: Dict[str, Any] = {}

    def get_json(self, silent: bool = False) -> Any:
        return {}


def abort(code: int) -> None:
    raise Exception(f"abort {code}")


request = Request()
FlaskRequest = Request


def flask_namespace() -> SimpleNamespace:
    return SimpleNamespace(
        Blueprint=FlaskBlueprint,
        Flask=FlaskType,
        Request=FlaskRequest,
        abort=abort,
        jsonify=jsonify,
        request=request,
        send_from_directory=send_from_directory,
    )


class RequestsRequestException(Exception):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.response: Any | None = None


class RequestsHTTPError(RequestsRequestException):
    def __init__(self, response: Any | None = None) -> None:
        super().__init__("HTTP error")
        self.response = response


class _DummyRequests:
    class exceptions:
        RequestException = RequestsRequestException
        HTTPError = RequestsHTTPError

    @staticmethod
    def post(*a: Any, **k: Any) -> None:
        raise RuntimeError("requests module not available")
