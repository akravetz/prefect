import datetime
import os
import shlex
import subprocess
import tempfile
import uuid

import pytest

import prefect
from prefect import configuration
from prefect.configuration import Config

template = b"""
    debug = false

    [general]
    x = 1
    y = "hi"

        [general.nested]
        x = "${general.x}"
        x_interpolated = "${general.x} + 1"
        y = "${general.y} or bye"

    [interpolation]
    key = "x"
    value = "${general.nested.${interpolation.key}}"
    bad_value = "${general.bad_key}"

    [env_vars]
    interpolated_path = "$PATH"
    interpolated_from_non_string_key_bool = "${env_vars.true}"
    interpolated_from_non_string_key_string = "${env_vars.true} string"
    not_interpolated_path = "xxx$PATHxxx"

    [logging]
    format = "log-format"

    [secrets]
    password = "1234"
    very_private = "000"
    """


class TestConfig:
    def test_is_dotdict(self):
        assert isinstance(Config(), prefect.utilities.collections.DotDict)

    def test_set_nested_creates_configs(self):
        config = Config()
        config.set_nested("a.b.c", 1)
        assert config.a.b.c == 1
        assert isinstance(config.a, Config)
        assert isinstance(config.a.b, Config)

    def test_set_nested_overwrites(self):
        config = Config()
        config.set_nested("a.b.c", 1)
        config.set_nested("a.b.d", 10)
        config.set_nested("a.b.c", 2)
        assert config.a.b.c == 2
        assert config.a.b.d == 10

    def test_set_nested_overwrites_values_with_more_configs(self):
        config = Config()
        config.set_nested("a.b", 1)
        config.set_nested("a.b.c", 2)
        config.set_nested("a.b.c.d", 3)
        assert config.a.b.c.d == 3

    def test_setdefault_nested_creates_configs(self):
        config = Config()
        config.setdefault_nested("a.b.c", 1)
        assert config.a.b.c == 1
        assert isinstance(config.a, Config)
        assert isinstance(config.a.b, Config)

    def test_setdefault_nested_overwrites_only_if_missing(self):
        config = Config()
        config.setdefault_nested("a.b.c", 1)
        config.setdefault_nested("a.b.d", 10)
        config.setdefault_nested("a.b.c", 2)
        assert config.a.b.c == 1
        assert config.a.b.d == 10

    def test_get_nested(self):
        config = Config()
        config.set_nested("a.b.c", 1)
        assert config.get_nested("a.b.c") == 1

    def test_get_nested_when_missing(self):
        assert Config().get_nested("a.b.c") is None

    def test_get_nested_default(self):
        assert Config().get_nested("a.b.c", 1) == 1

    def test_critical_key_protection_disabled(self):
        config = Config()
        assert not config.__protect_critical_keys__
        config.update = 1
        assert config.update == 1


@pytest.fixture
def test_config_file_path():
    with tempfile.NamedTemporaryFile() as test_config:
        test_config.write(template)
        test_config.seek(0)
        yield test_config.name


@pytest.fixture
def config(test_config_file_path, monkeypatch):

    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__NEW_KEY", "TEST")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__TWICE__NESTED__NEW_KEY", "TEST")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__TRUE", "true")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__FALSE", "false")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__INT", "10")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__NEGATIVE_INT", "-10")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__FLOAT", "7.5")
    monkeypatch.setenv("PREFECT_TEST__ENV_VARS__NEGATIVE_FLOAT", "-7.5")
    monkeypatch.setenv("PATH", "1/2/3")
    monkeypatch.setenv(
        "PREFECT_TEST__ENV_VARS__ESCAPED_CHARACTERS", r"line 1\nline 2\rand 3\tand 4"
    )

    yield configuration.load_configuration(
        test_config_file_path, env_var_prefix="PREFECT_TEST"
    )


def test_keys(config):
    assert "debug" in config
    assert "general" in config
    assert "nested" in config.general
    assert "x" not in config


def test_repr(config):
    assert (
        repr(config)
        == "<Config: 'debug', 'env_vars', 'general', 'interpolation', 'logging', 'secrets', 'tasks'>"
    )
    assert repr(config.general) == "<Config: 'nested', 'x', 'y'>"


def test_getattr_missing(config):
    with pytest.raises(AttributeError, match="Config has no key 'hello'"):
        config.hello


def test_debug(config):
    assert config.debug is False


def test_general(config):
    assert config.general.x == 1
    assert config.general.y == "hi"


def test_general_nested(config):
    assert config.general.nested.x == config.general.x == 1
    assert config.general.nested.x_interpolated == "1 + 1"
    assert config.general.nested.y == "hi or bye"


def test_interpolation(config):
    assert config.interpolation.value == config.general.nested.x == 1


def test_env_var_interpolation(config):
    assert config.env_vars.interpolated_path == os.environ.get("PATH")


def test_string_to_type_function():

    assert configuration.string_to_type("true") is True
    assert configuration.string_to_type("True") is True
    assert configuration.string_to_type("TRUE") is True
    assert configuration.string_to_type("trUe") is True
    assert configuration.string_to_type("false") is False
    assert configuration.string_to_type("False") is False
    assert configuration.string_to_type("FALSE") is False
    assert configuration.string_to_type("falSe") is False

    assert configuration.string_to_type("1") == 1
    assert configuration.string_to_type("1.5") == 1.5

    assert configuration.string_to_type("-1") == -1
    assert configuration.string_to_type("-1.5") == -1.5

    assert configuration.string_to_type("x") == "x"


def test_env_var_interpolation_with_type_assignment(config):
    assert config.env_vars.true is True
    assert config.env_vars.false is False
    assert config.env_vars.int == 10
    assert config.env_vars.negative_int == -10
    assert config.env_vars.float == 7.5
    assert config.env_vars.negative_float == -7.5


def test_env_var_interpolation_with_type_interpolation(config):
    assert config.env_vars.interpolated_from_non_string_key_bool is True
    assert config.env_vars.interpolated_from_non_string_key_string == "True string"


def test_env_var_interpolation_doesnt_match_internal_dollar_sign(config):
    assert config.env_vars.not_interpolated_path == "xxx$PATHxxx"


def test_env_var_interpolation_with_nonexistant_key(config):
    assert config.interpolation.bad_value == ""


def test_env_var_overrides_new_key(config):
    assert config.env_vars.new_key == "TEST"


def test_env_var_creates_nested_keys(config):
    assert config.env_vars.twice.nested.new_key == "TEST"


def test_env_var_escaped(config):
    assert config.env_vars.escaped_characters == "line 1\nline 2\rand 3\tand 4"


def test_copy_leaves_values_mutable(config):

    config.set_nested("x.y.z", [1])
    assert config.x.y.z == [1]
    new = config.copy()
    assert new.x.y.z == [1]
    new.x.y.z.append(2)
    assert config.x.y.z == [1, 2]


def test_copy_doesnt_make_keys_mutable(config):

    new = config.copy()
    new.general.z = 1
    assert "z" not in config.general


class TestUserConfig:
    def test_load_user_config(self, test_config_file_path):

        with tempfile.NamedTemporaryFile() as user_config:
            user_config.write(
                b"""
                [general]
                x = 2

                [user]
                foo = "bar"
                """
            )
            user_config.seek(0)
            config = configuration.load_configuration(
                path=test_config_file_path, user_config_path=user_config.name
            )

            # check that user values are loaded
            assert config.general.x == 2
            assert config.user.foo == "bar"

            # check that default values are preserved
            assert config.general.y == "hi"

            # check that interpolation takes place after user config is loaded
            assert config.general.nested.x == 2


class TestProcessTaskDefaults:
    def test_max_retries_is_0_if_not_set(self):
        config = configuration.process_task_defaults(Config())
        assert config.tasks.defaults.max_retries == 0

    def test_max_retries_is_0_if_false(self):
        config = Config()
        config.set_nested("tasks.defaults.max_retries", False)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.max_retries == 0

    def test_max_retries_is_0_if_none(self):
        config = Config()
        config.set_nested("tasks.defaults.max_retries", None)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.max_retries == 0

    def test_max_retries_is_0_if_0(self):
        config = Config()
        config.set_nested("tasks.defaults.max_retries", 0)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.max_retries == 0

    def test_max_retries_ignored_if_set(self):
        config = Config()
        config.set_nested("tasks.defaults.max_retries", 3)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.max_retries == 3

    def test_retry_delay_is_none_if_not_set(self):
        config = configuration.process_task_defaults(Config())
        assert config.tasks.defaults.retry_delay is None

    def test_retry_delay_is_none_if_false(self):
        config = Config()
        config.set_nested("tasks.defaults.retry_delay", False)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.retry_delay is None

    def test_retry_delay_is_none_if_none(self):
        config = Config()
        config.set_nested("tasks.defaults.retry_delay", None)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.retry_delay is None

    def test_retry_delay_is_timedelta_if_int(self):
        config = Config()
        config.set_nested("tasks.defaults.retry_delay", 5)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.retry_delay == datetime.timedelta(seconds=5)

    def test_retry_delay_is_timedelta_if_timedelta(self):
        config = Config()
        config.set_nested("tasks.defaults.retry_delay", datetime.timedelta(seconds=5))
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.retry_delay == datetime.timedelta(seconds=5)

    def test_timeout_is_none_if_not_set(self):
        config = configuration.process_task_defaults(Config())
        assert config.tasks.defaults.timeout is None

    def test_timeout_is_none_if_false(self):
        config = Config()
        config.set_nested("tasks.defaults.timeout", False)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.timeout is None

    def test_timeout_is_none_if_none(self):
        config = Config()
        config.set_nested("tasks.defaults.timeout", None)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.timeout is None

    def test_timeout_is_timedelta_if_int(self):
        config = Config()
        config.set_nested("tasks.defaults.timeout", 5)
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.timeout == datetime.timedelta(seconds=5)

    def test_timeout_is_timedelta_if_timedelta(self):
        config = Config()
        config.set_nested("tasks.defaults.timeout", datetime.timedelta(seconds=5))
        config = configuration.process_task_defaults(config)
        assert config.tasks.defaults.timeout == datetime.timedelta(seconds=5)


class TestConfigValidation:
    def test_invalid_keys_raise_error(self):

        with tempfile.NamedTemporaryFile() as test_config:
            test_config.write(
                b"""
                [outer]
                x = 1

                    [outer.keys]
                    a = "b"
                """
            )
            test_config.seek(0)

            with pytest.raises(ValueError):
                configuration.load_configuration(test_config.name)

    def test_invalid_env_var_raises_error(self, monkeypatch):
        monkeypatch.setenv("PREFECT_TEST__X__Y__KEYS__Z", "TEST")

        with tempfile.NamedTemporaryFile() as test_config:
            with pytest.raises(ValueError):
                configuration.load_configuration(
                    test_config.name, env_var_prefix="PREFECT_TEST"
                )

    def test_mixed_case_keys_are_ok(self):
        with tempfile.NamedTemporaryFile() as test_config:
            test_config.write(
                b"""
                [SeCtIoN]
                KeY = 1
                """
            )
            test_config.seek(0)

            config = configuration.load_configuration(test_config.name)

        assert "KeY" in config.SeCtIoN
        assert config.SeCtIoN.KeY == 1

    def test_env_vars_are_interpolated_as_lower_case(self, monkeypatch):

        monkeypatch.setenv("PREFECT_TEST__SECTION__KEY", "2")

        with tempfile.NamedTemporaryFile() as test_config:
            test_config.write(
                b"""
                [SeCtIoN]
                KeY = 1
                """
            )
            test_config.seek(0)

            config = configuration.load_configuration(
                test_config.name, env_var_prefix="PREFECT_TEST"
            )

        assert "KeY" in config.SeCtIoN
        assert config.SeCtIoN.KeY == 1
        assert config.section.key == 2
