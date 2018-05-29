import inspect
from datetime import timedelta
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import prefect
from prefect.utilities.json import ObjectAttributesCodec, Serializable


class Task(Serializable):

    _json_codec = ObjectAttributesCodec

    def __init__(
            self,
            name: Optional[str] = None,
            slug: Optional[str] = None,
            description: Optional[str] = None,
            group: Optional[str] = None,
            tags: Optional[Iterable[str]] = None,
            max_retries: int = 0,
            retry_delay: timedelta = timedelta(minutes=1),
            timeout=None,
            trigger=None,
            secrets=None) -> None:

        self.name = name or type(self).__name__
        self.slug = slug
        self.description = description

        self.group = str(group or prefect.context.get('group', ''))
        self.tags = set(tags or prefect.context.get('tags', []))

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.trigger = trigger or prefect.triggers.all_successful

        self.secrets = secrets

        flow: Optional['prefect.Flow'] = prefect.context.get('flow')
        if flow:
            flow.add_task(self)

    def __repr__(self) -> str:
        return '<Task: {self.name}>'.format(cls=type(self).__name__, self=self)

    # Run  --------------------------------------------------------------------

    def inputs(self) -> Tuple[str]:
        return tuple(inspect.signature(self.run).parameters.keys())

    def run(self):
        """
        The main entrypoint for tasks.

        In addition to running arbitrary functions, tasks can interact with
        Prefect in a few ways:
            1. Return an optional result. When this function runs successfully,
                the task is considered successful and the result (if any) is
                made available to downstream edges.
            2. Raise an error. Errors are interpreted as failure.
            3. Raise a signal. Signals can include FAIL, SUCCESS, WAIT, etc.
                and indicate that the task should be put in the indicated
                state.
                - FAIL will lead to retries if appropriate
                - WAIT will end execution and skip all downstream tasks with
                    state WAITING_FOR_UPSTREAM (unless appropriate triggers
                    are set). The task can be run again and should check
                    context.is_waiting to see if it was placed in a WAIT.
        """
        raise NotImplementedError()

    # Dependencies -------------------------------------------------------------

    def __call__(self, *args, upstream_tasks=None, **kwargs):
        # this will raise an error if callargs weren't all provided
        signature = inspect.signature(self.run)
        callargs = dict(signature.bind(*args, **kwargs).arguments)

        # bind() compresses all variable keyword arguments, so we expand them
        var_kw_arg = inspect.getfullargspec(self.run).varkw
        callargs.update(callargs.pop(var_kw_arg, {}))

        flow = prefect.context.get('flow', prefect.flow.Flow())
        return self.set_dependencies(
            flow=flow,
            upstream_tasks=upstream_tasks,
            keyword_results=callargs,
        )

    def set_dependencies(
            self,
            flow: Optional['prefect.Flow'] = None,
            upstream_tasks: Optional[Iterable['Task']] = None,
            downstream_tasks: Optional[Iterable['Task']] = None,
            keyword_results=None,
            validate: bool = True):

        if flow is None:
            flow = prefect.context.get('flow',
                                       prefect.Flow())  # type: 'prefect.Flow'

        return flow.set_dependencies(
            task=self,
            upstream_tasks=upstream_tasks,
            downstream_tasks=downstream_tasks,
            keyword_results=keyword_results,
            validate=validate)

    # Operators ----------------------------------------------------------------

    # Serialization ------------------------------------------------------------

    def serialize(self) -> Dict[str, Any]:

        serialized = dict(
            name=self.name,
            slug=self.slug,
            type=type(self).__name__,
            description=self.description,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            timeout=self.timeout,
            trigger=self.trigger)

        return serialized

    # @classmethod
    # def deserialize(cls, serialized):
    #     if serialized.get('qualified_name') == 'prefect.task.Parameter':
    #         serialized.pop('qualified_name')
    #         return Parameter.deserialize(serialized)

    #     task = Task(
    #         name=serialized['name'],
    #         description=serialized['description'],
    #         max_retries=serialized['max_retries'],
    #         retry_delay=serialized['retry_delay'],
    #         timeout=serialized['timeout'],
    #         trigger=serialized['trigger'])

    #     return task


class Parameter(Task):
    """
    A Parameter is a special task that defines a required flow input.
    """

    def __init__(
            self, name: str, default: Optional[Any] = None,
            required: bool = True) -> None:
        """
        Args:
            name (str): the Parameter name.

            required (bool): If True, the Parameter is required and the default
                value is ignored.

            default (any): A default value for the parameter. If the default
                is not None, the Parameter will not be required.
        """
        if default is not None:
            required = False

        self.required = required
        self.default = default

        super().__init__(name=name)

    def run(self) -> Any:
        params = prefect.context.get('parameters', {})
        if self.required and self.name not in params:
            raise prefect.signals.FAIL(
                'Parameter "{}" was required but not provided.'.format(
                    self.name))
        return params.get(self.name, self.default)

    def serialize(self) -> Dict[str, Any]:
        serialized = super().serialize()
        serialized.update(required=self.required, default=self.default)
        return serialized

    @classmethod
    def deserialize(cls, serialized):
        parameter = super().deserialize(serialized)
        parameter.required = serialized['required']
        parameter.default = serialized['default']
        return parameter
