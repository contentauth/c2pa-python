import pytest
import tempfile
from pathlib import Path
from c2pa.c2pa import (
    C2paError,
    C2paSigningAlg,
    C2paSignerInfo,
    Stream,
    Reader,
    Builder,
    Signer,
    version,
    load_settings,
    read_file,
    read_ingredient_file,
    sign_file,
    format_embeddable,
    ed25519_sign,
)

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "fixtures"

# Test files
UNSIGNED_FILE = TEST_DATA_DIR / "A.jpg"
SIGNED_FILE = TEST_DATA_DIR / "C.jpg"
CERT_FILE = TEST_DATA_DIR / "es256_certs.pem"
KEY_FILE = TEST_DATA_DIR / "es256_private.key"

@pytest.fixture
def unsigned_file():
    """Fixture providing path to unsigned test file."""
    assert UNSIGNED_FILE.exists(), f"Test file {UNSIGNED_FILE} not found"
    return UNSIGNED_FILE

@pytest.fixture
def signed_file():
    """Fixture providing path to signed test file."""
    assert SIGNED_FILE.exists(), f"Test file {SIGNED_FILE} not found"
    return SIGNED_FILE

@pytest.fixture
def cert_data():
    """Fixture providing certificate data."""
    assert CERT_FILE.exists(), f"Certificate file {CERT_FILE} not found"
    with open(CERT_FILE, 'rb') as f:
        return f.read()

@pytest.fixture
def key_data():
    """Fixture providing private key data."""
    assert KEY_FILE.exists(), f"Key file {KEY_FILE} not found"
    with open(KEY_FILE, 'rb') as f:
        return f.read()

@pytest.fixture
def signer_info(cert_data, key_data):
    """Fixture providing C2paSignerInfo with valid certificate and key."""
    return C2paSignerInfo(
        alg=b"ES256",
        sign_cert=cert_data,
        private_key=key_data,
        ta_url=None  #b"http://test.tsa"
    )

def test_version():
    """Test that version() returns a non-empty string."""
    v = version()
    assert isinstance(v, str)
    assert len(v) > 0

def test_load_settings():
    """Test loading settings."""
    settings = '{"test": "value"}'
    load_settings(settings)
    # No exception means success

def test_read_unsigned_file(unsigned_file):
    """Test reading an unsigned JPEG file."""
    with pytest.raises(C2paError.ManifestNotFound) as exc_info:
        read_file(unsigned_file)
    assert "ManifestNotFound" in str(exc_info.value)

def test_read_signed_file(signed_file):
    """Test reading a signed JPEG file with C2PA manifest."""
    manifest = read_file(signed_file)
    assert isinstance(manifest, str)
    assert len(manifest) > 0
    # Verify it's valid JSON
    import json
    manifest_data = json.loads(manifest)
    assert isinstance(manifest_data, dict)
    print(manifest_data)
    # Verify it has expected C2PA structure
    #assert "claim_generator" in manifest_data
    assert "active_manifest" in manifest_data
    #assert "format" in manifest_data

def test_read_ingredient_file(unsigned_file):
    """Test reading a JPEG file as an ingredient."""
    ingredient = read_ingredient_file(unsigned_file)
    assert isinstance(ingredient, str)
    # Verify it's valid JSON
    import json
    ingredient_data = json.loads(ingredient)
    assert isinstance(ingredient_data, dict)
    # Verify it has expected ingredient structure
    assert "format" in ingredient_data
    assert "title" in ingredient_data

def test_stream(unsigned_file):
    """Test Stream class with a real file."""
    with open(unsigned_file, 'rb') as f:
        stream = Stream(f)
        assert stream._stream is not None
        stream.close()

def test_reader_unsigned(unsigned_file):
    """Test Reader class with an unsigned file."""
    reader = Reader(unsigned_file)
    assert reader._reader is not None
    
    try:
        manifest = reader.json()
        assert manifest is None  # Unsigned file should have no manifest
    except C2paError as e:
        # This is expected if the file isn't a valid C2PA file
        assert "not a valid C2PA file" in str(e)
    
    reader.close()

def test_reader_signed(signed_file):
    """Test Reader class with a signed file."""
    reader = Reader(signed_file)
    assert reader._reader is not None
    
    manifest = reader.json()
    assert isinstance(manifest, str)
    assert len(manifest) > 0
    
    # Verify it's valid JSON
    import json
    manifest_data = json.loads(manifest)
    assert isinstance(manifest_data, dict)
    assert "claim_generator" in manifest_data
    
    reader.close()

def test_signer(signer_info):
    """Test Signer class creation and operations."""
    # Test creating signer from info
    signer = Signer.from_info(signer_info)
    assert signer._signer is not None
    
    # Test reserve_size
    try:
        size = signer.reserve_size()
        assert isinstance(size, int)
        assert size >= 0
    except C2paError as e:
        # This is expected if the signer info is invalid
        assert "invalid signer info" in str(e)
    
    signer.close()
    
    # Test creating signer from callback
    def test_callback(data: bytes) -> bytes:
        return b"test_signature"
    
    signer = Signer.from_callback(
        callback=test_callback,
        alg=C2paSigningAlg.ES256,
        certs=cert_data.decode('utf-8'),
        tsa_url="http://test.tsa"
    )
    assert signer._signer is not None
    signer.close()

def test_builder(unsigned_file):
    """Test Builder class operations with a real file."""
    # Test creating builder from JSON
    manifest_json = '{"test": "value"}'
    builder = Builder.from_json(manifest_json)
    assert builder._builder is not None
    
    # Test builder operations
    builder.set_no_embed()
    builder.set_remote_url("http://test.url")
    
    # Test adding resource
    with open(unsigned_file, 'rb') as f:
        builder.add_resource("test_uri", f)
    
    # Test adding ingredient
    ingredient_json = '{"test": "ingredient"}'
    with open(unsigned_file, 'rb') as f:
        builder.add_ingredient(ingredient_json, "image/jpeg", f)
    
    builder.close()

def test_ed25519_sign():
    """Test Ed25519 signing."""
    data = b"test data"
    private_key = "test_private_key"
    
    try:
        signature = ed25519_sign(data, private_key)
        assert isinstance(signature, bytes)
        assert len(signature) == 64  # Ed25519 signatures are always 64 bytes
    except C2paError as e:
        # This is expected if the private key is invalid
        assert "invalid private key" in str(e)
    except Exception as e:
        # Catch any other unexpected exceptions
        assert False, f"Unexpected exception: {str(e)}"
    # Test with invalid data
def test_format_embeddable():
    """Test formatting embeddable manifest."""
    format_str = "image/jpeg"
    manifest_bytes = b"test manifest"
    
    try:
        size, result = format_embeddable(format_str, manifest_bytes)
        assert isinstance(size, int)
        assert size >= 0
        assert isinstance(result, bytes)
        assert len(result) == size
    except C2paError as e:
        # This is expected if the format or manifest is invalid
        assert "invalid format" in str(e) or "invalid manifest" in str(e)

def test_context_managers(unsigned_file, signed_file, signer_info):
    """Test context manager functionality with real files."""
    # Test Reader context manager with unsigned file
    with Reader(unsigned_file) as reader:
        assert reader._reader is not None
        try:
            manifest = reader.json()
            assert manifest is None  # Unsigned file should have no manifest
        except C2paError:
            pass
    
    # Test Reader context manager with signed file
    with Reader(signed_file) as reader:
        assert reader._reader is not None
        manifest = reader.json()
        assert isinstance(manifest, str)
        assert len(manifest) > 0
    
    # Test Signer context manager
    with Signer.from_info(signer_info) as signer:
        assert signer._signer is not None
        try:
            size = signer.reserve_size()
            assert isinstance(size, int)
            assert size >= 0
        except C2paError:
            pass
    
    # Test Builder context manager
    manifest_json = '{"test": "value"}'
    with Builder.from_json(manifest_json) as builder:
        assert builder._builder is not None
        builder.set_no_embed()
        builder.set_remote_url("http://test.url") 