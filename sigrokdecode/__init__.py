"""Python implementation of sigrok tools"""
import abc
from typing import (
    Optional,
    overload,
    List,
    Set,
    Tuple,
    Any,
    Callable,
    Sequence,
    Dict,
    Union,
    TypedDict,
)
from enum import Enum
import sys

from sigrokdecode.input import Input

if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points
import functools

__version__ = "0.4.2"


class OutputType(Enum):
    ANN = 0
    PYTHON = 1
    BINARY = 2
    LOGIC = 3
    META = 4


class MetadataKeys(Enum):
    CONF_SAMPLERATE = 1


# define at top-level for backwards compatibility with the official sigrokdecode api
SRD_CONF_SAMPLERATE = MetadataKeys.CONF_SAMPLERATE

OUTPUT_ANN = OutputType.ANN
OUTPUT_PYTHON = OutputType.PYTHON
OUTPUT_BINARY = OutputType.BINARY
OUTPUT_LOGIC = OutputType.LOGIC
OUTPUT_META = OutputType.META

DataTypeAnn = Tuple[int, List[str]]
DataTypePython = Any
DataTypeBinary = Tuple[int, List[bytes]]
DataTypeLogic = Tuple[int, bytes]
DataTypeMeta = Any

DataType = Union[
    DataTypeAnn,
    DataTypePython,
    DataTypeBinary,
    DataTypeLogic,
    DataTypeMeta,
]


def SR_KHZ(num):
    return num * 1000


def SR_MHZ(num):
    return SR_KHZ(num) * 1000


class DecoderChannels(TypedDict):
    id: str
    name: str
    desc: str


class DecoderOptions(TypedDict):
    id: str
    desc: str
    default: str
    values: Tuple[str, ...]


class Decoder(abc.ABC):
    # __init__() won't get called by subclasses
    api_version: int
    id: str
    name: str
    longname: str
    desc: str
    license: str
    inputs: Sequence[str]
    outputs: Sequence[str]
    channels: Sequence[DecoderChannels]
    optional_channels: Optional[Sequence[DecoderChannels]] = None
    options: Optional[Tuple[DecoderOptions, ...]] = None
    annotations: Optional[Sequence[Tuple[str, str]]] = None
    annotation_rows: Optional[Sequence[Tuple[str, str, Tuple[int, ...]]]] = None
    binary: Optional[Sequence[Tuple[str, str]]] = None
    tags: Optional[Sequence[str]] = None

    decoder_channel_to_data_channel: Dict[int, int] = {}
    one_to_one: bool = False
    input: Optional[Input] = None
    callbacks: Dict[
        OutputType,
        Set[Tuple[Any, Callable[[int, int, DataType], None]]],
    ] = {}

    def register(self, output_type: OutputType, proto_id=None, meta=None) -> OutputType:
        """
        This function is used to register the output that will be generated by the
        decoder, its argument should be one of :class:`OutputType`. The function
        returns an identifier that can then be used as the output_id argument of the
        put() function.

        :param output_type:
        :param proto_id:
        :param meta:
        :return:
        """
        # print("register", output_type, meta)
        return output_type

    def metadata(self, key: MetadataKeys, value: Any) -> None:
        """
        Used to pass the decoder metadata about the data stream. Currently, the only
        value for key is sigrokdecode.SRD_CONF_SAMPLERATE, value is then the sample
        rate of the data stream in Hz.

        This function can be called multiple times, so make sure your protocol
        decoder handles this correctly! Do not place statements in there that depend
        on metadata to be called only once.
        """
        # Backup for decoders that don't care.
        pass

    def add_callback(self, output_type: OutputType, output_filter, fun) -> None:
        # print(output_type, output_filter, fun)
        if not hasattr(self, "callbacks"):
            self.callbacks = {}

        if output_type not in self.callbacks:
            self.callbacks[output_type] = set()

        self.callbacks[output_type].add((output_filter, fun))

    def wait(self, conds=[]):
        assert self.input is not None, "Decoder not initialized"
        if isinstance(conds, dict):
            conds = [conds]
        if self.one_to_one:
            data_conds = conds
        else:
            data_conds = []
            for cond in conds:
                data_cond = {}
                for k in cond:
                    if k == "skip":
                        data_cond["skip"] = cond[k]
                    else:
                        data_cond[self.decoder_channel_to_data_channel[k]] = cond[k]
                data_conds.append(data_cond)

        raw_data = self.input.wait(data_conds)
        data = [None] * (
            len(type(self).channels) + len(getattr(type(self), "optional_channels", []))
        )
        for decoder_channel in self.decoder_channel_to_data_channel:
            data_channel = self.decoder_channel_to_data_channel[decoder_channel]
            data[decoder_channel] = raw_data[data_channel]

        return tuple(data)

    def put(
        self, startsample: int, endsample: int, output_id: OutputType, data: DataType
    ) -> None:
        # print(startsample, endsample, output_id, data)
        if output_id not in self.callbacks:
            return
        for output_filter, cb in self.callbacks[output_id]:
            if output_filter is not None:
                if output_id == OUTPUT_ANN:
                    assert (
                        self.annotations is not None
                    ), "Decoder does not support annotations."
                    annotation = self.annotations[data[0]]
                    if annotation[0] != output_filter:
                        continue
                elif output_id == OUTPUT_BINARY:
                    assert self.binary is not None, "Decoder does not support binary"
                    track = self.binary[data[0]]
                    if track[0] != output_filter:
                        continue
            cb(startsample, endsample, data)

    def set_channelnum(self, channelname: str, channelnum: int) -> None:
        if not hasattr(self, "decoder_channel_to_data_channel"):
            self.decoder_channel_to_data_channel = {}
            self.one_to_one = True

        self_class = type(self)

        optional_channels = (
            list()
            if self_class.optional_channels is None
            else list(self_class.optional_channels)
        )
        channels = list() if self_class.channels is None else list(self_class.channels)

        for i, c in enumerate(channels + optional_channels):
            if c["id"] == channelname:
                self.decoder_channel_to_data_channel[i] = channelnum
                self.one_to_one = self.one_to_one and i == channelnum
                break

    def has_channel(self, decoder_channel: int) -> bool:
        return decoder_channel in self.decoder_channel_to_data_channel

    @property
    def samplenum(self) -> Optional[int]:
        """must be called after wait() to be non-None"""
        assert self.input is not None
        return self.input.samplenum

    @property
    def matched(self) -> Optional[List[bool]]:
        """must be called after wait() to be non-None"""
        assert self.input is not None
        return self.input.matched

    @overload
    @abc.abstractmethod
    def decode(self) -> None:
        """
        In non-stacked decoders, this function is called by the libsigrokdecode
        backend to start the decoding.

        It takes no arguments, but instead will enter an infinite loop and gets
        samples by calling the more versatile wait() method. This frees specific
        protocol decoders from tedious yet common tasks like detecting edges,
        or sampling signals at specific points in time relative to the current position.

        Note: This decode(self) method's signature has been introduced in version 3
        of the protocol decoder API, in previous versions only decode(self,
        startsample, endsample, data) was available.
        """
        ...

    @overload
    @abc.abstractmethod
    def decode(self, startsample: int, endsample: int, data: DataType) -> None:
        """
        In stacked decoders, this is a function that is called by the libsigrokdecode
        backend whenever it has a chunk of data for the protocol decoder to handle.
        """
        ...

    @abc.abstractmethod
    def decode(
        self,
        startsample: Optional[int] = None,
        endsample: Optional[int] = None,
        data: Optional[DataType] = None,
    ) -> None:
        ...

    def run(self, input_: Input):
        self.input = input_
        try:
            self.decode()
        except EOFError:
            pass

    def stop(self):
        pass


def get_decoder(decoder_id):
    discovered_plugins = entry_points(name=decoder_id, group="pysigrok.decoders")
    if len(discovered_plugins) == 1:
        return discovered_plugins[0].load()
    raise RuntimeError(
        "Decoder id ambiguous:" + ",".join([p.name for p in discovered_plugins])
    )


def cond_matches(cond, last_sample, current_sample):
    matches = True
    for channel in cond:
        if channel == "skip":
            return cond["skip"] == 0
        state = cond[channel]
        mask = 1 << channel
        last_value = last_sample & mask
        value = current_sample & mask
        if (
            (state == "l" and value != 0)
            or (state == "h" and value == 0)
            or (state == "r" and not (last_value == 0 and value != 0))
            or (state == "f" and not (last_value != 0 and value == 0))
            or (state == "e" and last_value == value)
            or (state == "s" and last_value != value)
        ):
            matches = False
            break
    return matches


def run_decoders(
    input_, output, decoders=[], output_type=OUTPUT_ANN, output_filter=None
):
    input_.add_callback(OUTPUT_PYTHON, None, functools.partial(output.output, input_))

    all_decoders = []
    next_decoder = None
    for decoder_info in reversed(decoders):
        decoder_class = decoder_info["cls"]
        decoder = decoder_class()
        all_decoders.insert(0, decoder)
        decoder.options = decoder_info["options"]

        for decoder_id in decoder_info["pin_mapping"]:
            channelnum = decoder_info["pin_mapping"][decoder_id]
            decoder.set_channelnum(decoder_id, channelnum)

        decoder.add_callback(
            output_type, output_filter, functools.partial(output.output, decoder)
        )
        if next_decoder:
            decoder.add_callback(output_type, output_filter, next_decoder.decode)
        next_decoder = decoder
        output_type = OUTPUT_PYTHON
        output_filter = None

    if all_decoders:
        first_decoder = all_decoders[0]
    else:
        first_decoder = output
    for d in all_decoders:
        d.reset()
    output.reset()

    if input_.samplerate > 0:
        first_decoder.metadata(SRD_CONF_SAMPLERATE, input_.samplerate)

    output.start()
    for d in all_decoders:
        d.start()

    first_decoder.run(input_)

    for d in all_decoders:
        d.stop()
    output.stop()
