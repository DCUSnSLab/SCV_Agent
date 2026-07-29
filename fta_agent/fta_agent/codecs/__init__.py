"""코덱 플러그인 패키지 — import 시 각 구현체가 레지스트리에 자기등록된다."""
from . import cbor_codec  # noqa: F401
from . import cdr_zstd  # noqa: F401
from . import jpeg  # noqa: F401
from . import voxel_zstd  # noqa: F401
