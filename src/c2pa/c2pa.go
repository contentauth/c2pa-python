package c2pa

// #include <c2pa.h>
import "C"

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"runtime"
	"sync"
	"sync/atomic"
	"unsafe"
)

type RustBuffer = C.RustBuffer

type RustBufferI interface {
	AsReader() *bytes.Reader
	Free()
	ToGoBytes() []byte
	Data() unsafe.Pointer
	Len() int
	Capacity() int
}

func RustBufferFromExternal(b RustBufferI) RustBuffer {
	return RustBuffer{
		capacity: C.int(b.Capacity()),
		len:      C.int(b.Len()),
		data:     (*C.uchar)(b.Data()),
	}
}

func (cb RustBuffer) Capacity() int {
	return int(cb.capacity)
}

func (cb RustBuffer) Len() int {
	return int(cb.len)
}

func (cb RustBuffer) Data() unsafe.Pointer {
	return unsafe.Pointer(cb.data)
}

func (cb RustBuffer) AsReader() *bytes.Reader {
	b := unsafe.Slice((*byte)(cb.data), C.int(cb.len))
	return bytes.NewReader(b)
}

func (cb RustBuffer) Free() {
	rustCall(func(status *C.RustCallStatus) bool {
		C.ffi_c2pa_rustbuffer_free(cb, status)
		return false
	})
}

func (cb RustBuffer) ToGoBytes() []byte {
	return C.GoBytes(unsafe.Pointer(cb.data), C.int(cb.len))
}

func stringToRustBuffer(str string) RustBuffer {
	return bytesToRustBuffer([]byte(str))
}

func bytesToRustBuffer(b []byte) RustBuffer {
	if len(b) == 0 {
		return RustBuffer{}
	}
	// We can pass the pointer along here, as it is pinned
	// for the duration of this call
	foreign := C.ForeignBytes{
		len:  C.int(len(b)),
		data: (*C.uchar)(unsafe.Pointer(&b[0])),
	}

	return rustCall(func(status *C.RustCallStatus) RustBuffer {
		return C.ffi_c2pa_rustbuffer_from_bytes(foreign, status)
	})
}

type BufLifter[GoType any] interface {
	Lift(value RustBufferI) GoType
}

type BufLowerer[GoType any] interface {
	Lower(value GoType) RustBuffer
}

type FfiConverter[GoType any, FfiType any] interface {
	Lift(value FfiType) GoType
	Lower(value GoType) FfiType
}

type BufReader[GoType any] interface {
	Read(reader io.Reader) GoType
}

type BufWriter[GoType any] interface {
	Write(writer io.Writer, value GoType)
}

type FfiRustBufConverter[GoType any, FfiType any] interface {
	FfiConverter[GoType, FfiType]
	BufReader[GoType]
}

func LowerIntoRustBuffer[GoType any](bufWriter BufWriter[GoType], value GoType) RustBuffer {
	// This might be not the most efficient way but it does not require knowing allocation size
	// beforehand
	var buffer bytes.Buffer
	bufWriter.Write(&buffer, value)

	bytes, err := io.ReadAll(&buffer)
	if err != nil {
		panic(fmt.Errorf("reading written data: %w", err))
	}
	return bytesToRustBuffer(bytes)
}

func LiftFromRustBuffer[GoType any](bufReader BufReader[GoType], rbuf RustBufferI) GoType {
	defer rbuf.Free()
	reader := rbuf.AsReader()
	item := bufReader.Read(reader)
	if reader.Len() > 0 {
		// TODO: Remove this
		leftover, _ := io.ReadAll(reader)
		panic(fmt.Errorf("Junk remaining in buffer after lifting: %s", string(leftover)))
	}
	return item
}

func rustCallWithError[U any](converter BufLifter[error], callback func(*C.RustCallStatus) U) (U, error) {
	var status C.RustCallStatus
	returnValue := callback(&status)
	err := checkCallStatus(converter, status)

	return returnValue, err
}

func checkCallStatus(converter BufLifter[error], status C.RustCallStatus) error {
	switch status.code {
	case 0:
		return nil
	case 1:
		return converter.Lift(status.errorBuf)
	case 2:
		// when the rust code sees a panic, it tries to construct a rustbuffer
		// with the message.  but if that code panics, then it just sends back
		// an empty buffer.
		if status.errorBuf.len > 0 {
			panic(fmt.Errorf("%s", FfiConverterStringINSTANCE.Lift(status.errorBuf)))
		} else {
			panic(fmt.Errorf("Rust panicked while handling Rust panic"))
		}
	default:
		return fmt.Errorf("unknown status code: %d", status.code)
	}
}

func checkCallStatusUnknown(status C.RustCallStatus) error {
	switch status.code {
	case 0:
		return nil
	case 1:
		panic(fmt.Errorf("function not returning an error returned an error"))
	case 2:
		// when the rust code sees a panic, it tries to construct a rustbuffer
		// with the message.  but if that code panics, then it just sends back
		// an empty buffer.
		if status.errorBuf.len > 0 {
			panic(fmt.Errorf("%s", FfiConverterStringINSTANCE.Lift(status.errorBuf)))
		} else {
			panic(fmt.Errorf("Rust panicked while handling Rust panic"))
		}
	default:
		return fmt.Errorf("unknown status code: %d", status.code)
	}
}

func rustCall[U any](callback func(*C.RustCallStatus) U) U {
	returnValue, err := rustCallWithError(nil, callback)
	if err != nil {
		panic(err)
	}
	return returnValue
}

func writeInt8(writer io.Writer, value int8) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeUint8(writer io.Writer, value uint8) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeInt16(writer io.Writer, value int16) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeUint16(writer io.Writer, value uint16) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeInt32(writer io.Writer, value int32) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeUint32(writer io.Writer, value uint32) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeInt64(writer io.Writer, value int64) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeUint64(writer io.Writer, value uint64) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeFloat32(writer io.Writer, value float32) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func writeFloat64(writer io.Writer, value float64) {
	if err := binary.Write(writer, binary.BigEndian, value); err != nil {
		panic(err)
	}
}

func readInt8(reader io.Reader) int8 {
	var result int8
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readUint8(reader io.Reader) uint8 {
	var result uint8
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readInt16(reader io.Reader) int16 {
	var result int16
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readUint16(reader io.Reader) uint16 {
	var result uint16
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readInt32(reader io.Reader) int32 {
	var result int32
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readUint32(reader io.Reader) uint32 {
	var result uint32
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readInt64(reader io.Reader) int64 {
	var result int64
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readUint64(reader io.Reader) uint64 {
	var result uint64
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readFloat32(reader io.Reader) float32 {
	var result float32
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func readFloat64(reader io.Reader) float64 {
	var result float64
	if err := binary.Read(reader, binary.BigEndian, &result); err != nil {
		panic(err)
	}
	return result
}

func init() {

	(&FfiConverterCallbackInterfaceSignerCallback{}).register()
	(&FfiConverterCallbackInterfaceStream{}).register()
	uniffiCheckChecksums()
}

func uniffiCheckChecksums() {
	// Get the bindings contract version from our ComponentInterface
	bindingsContractVersion := 24
	// Get the scaffolding contract version by calling the into the dylib
	scaffoldingContractVersion := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint32_t {
		return C.ffi_c2pa_uniffi_contract_version(uniffiStatus)
	})
	if bindingsContractVersion != int(scaffoldingContractVersion) {
		// If this happens try cleaning and rebuilding your project
		panic(fmt.Sprintf("c2pa: UniFFI contract version mismatch bindingsContractVersion=%d scaffoldingContractVersion=%d", bindingsContractVersion, int(scaffoldingContractVersion)))
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_func_sdk_version(uniffiStatus)
		})
		if checksum != 37245 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_func_sdk_version: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_func_version(uniffiStatus)
		})
		if checksum != 61576 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_func_version: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_add_ingredient(uniffiStatus)
		})
		if checksum != 54967 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_add_ingredient: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_add_resource(uniffiStatus)
		})
		if checksum != 12018 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_add_resource: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_from_archive(uniffiStatus)
		})
		if checksum != 17341 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_from_archive: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_sign(uniffiStatus)
		})
		if checksum != 8729 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_sign: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_to_archive(uniffiStatus)
		})
		if checksum != 44718 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_to_archive: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_with_json(uniffiStatus)
		})
		if checksum != 29392 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_with_json: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_from_stream(uniffiStatus)
		})
		if checksum != 3255 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_from_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_json(uniffiStatus)
		})
		if checksum != 33242 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_json: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_resource_to_stream(uniffiStatus)
		})
		if checksum != 44049 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_resource_to_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_constructor_builder_new(uniffiStatus)
		})
		if checksum != 8924 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_constructor_builder_new: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_constructor_callbacksigner_new(uniffiStatus)
		})
		if checksum != 51503 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_constructor_callbacksigner_new: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_constructor_reader_new(uniffiStatus)
		})
		if checksum != 7340 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_constructor_reader_new: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_signercallback_sign(uniffiStatus)
		})
		if checksum != 15928 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_signercallback_sign: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_stream_read_stream(uniffiStatus)
		})
		if checksum != 4594 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_stream_read_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_stream_seek_stream(uniffiStatus)
		})
		if checksum != 32219 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_stream_seek_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_stream_write_stream(uniffiStatus)
		})
		if checksum != 37641 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_stream_write_stream: UniFFI API checksum mismatch")
		}
	}
}

type FfiConverterUint64 struct{}

var FfiConverterUint64INSTANCE = FfiConverterUint64{}

func (FfiConverterUint64) Lower(value uint64) C.uint64_t {
	return C.uint64_t(value)
}

func (FfiConverterUint64) Write(writer io.Writer, value uint64) {
	writeUint64(writer, value)
}

func (FfiConverterUint64) Lift(value C.uint64_t) uint64 {
	return uint64(value)
}

func (FfiConverterUint64) Read(reader io.Reader) uint64 {
	return readUint64(reader)
}

type FfiDestroyerUint64 struct{}

func (FfiDestroyerUint64) Destroy(_ uint64) {}

type FfiConverterInt64 struct{}

var FfiConverterInt64INSTANCE = FfiConverterInt64{}

func (FfiConverterInt64) Lower(value int64) C.int64_t {
	return C.int64_t(value)
}

func (FfiConverterInt64) Write(writer io.Writer, value int64) {
	writeInt64(writer, value)
}

func (FfiConverterInt64) Lift(value C.int64_t) int64 {
	return int64(value)
}

func (FfiConverterInt64) Read(reader io.Reader) int64 {
	return readInt64(reader)
}

type FfiDestroyerInt64 struct{}

func (FfiDestroyerInt64) Destroy(_ int64) {}

type FfiConverterString struct{}

var FfiConverterStringINSTANCE = FfiConverterString{}

func (FfiConverterString) Lift(rb RustBufferI) string {
	defer rb.Free()
	reader := rb.AsReader()
	b, err := io.ReadAll(reader)
	if err != nil {
		panic(fmt.Errorf("reading reader: %w", err))
	}
	return string(b)
}

func (FfiConverterString) Read(reader io.Reader) string {
	length := readInt32(reader)
	buffer := make([]byte, length)
	read_length, err := reader.Read(buffer)
	if err != nil {
		panic(err)
	}
	if read_length != int(length) {
		panic(fmt.Errorf("bad read length when reading string, expected %d, read %d", length, read_length))
	}
	return string(buffer)
}

func (FfiConverterString) Lower(value string) RustBuffer {
	return stringToRustBuffer(value)
}

func (FfiConverterString) Write(writer io.Writer, value string) {
	if len(value) > math.MaxInt32 {
		panic("String is too large to fit into Int32")
	}

	writeInt32(writer, int32(len(value)))
	write_length, err := io.WriteString(writer, value)
	if err != nil {
		panic(err)
	}
	if write_length != len(value) {
		panic(fmt.Errorf("bad write length when writing string, expected %d, written %d", len(value), write_length))
	}
}

type FfiDestroyerString struct{}

func (FfiDestroyerString) Destroy(_ string) {}

type FfiConverterBytes struct{}

var FfiConverterBytesINSTANCE = FfiConverterBytes{}

func (c FfiConverterBytes) Lower(value []byte) RustBuffer {
	return LowerIntoRustBuffer[[]byte](c, value)
}

func (c FfiConverterBytes) Write(writer io.Writer, value []byte) {
	if len(value) > math.MaxInt32 {
		panic("[]byte is too large to fit into Int32")
	}

	writeInt32(writer, int32(len(value)))
	write_length, err := writer.Write(value)
	if err != nil {
		panic(err)
	}
	if write_length != len(value) {
		panic(fmt.Errorf("bad write length when writing []byte, expected %d, written %d", len(value), write_length))
	}
}

func (c FfiConverterBytes) Lift(rb RustBufferI) []byte {
	return LiftFromRustBuffer[[]byte](c, rb)
}

func (c FfiConverterBytes) Read(reader io.Reader) []byte {
	length := readInt32(reader)
	buffer := make([]byte, length)
	read_length, err := reader.Read(buffer)
	if err != nil {
		panic(err)
	}
	if read_length != int(length) {
		panic(fmt.Errorf("bad read length when reading []byte, expected %d, read %d", length, read_length))
	}
	return buffer
}

type FfiDestroyerBytes struct{}

func (FfiDestroyerBytes) Destroy(_ []byte) {}

// Below is an implementation of synchronization requirements outlined in the link.
// https://github.com/mozilla/uniffi-rs/blob/0dc031132d9493ca812c3af6e7dd60ad2ea95bf0/uniffi_bindgen/src/bindings/kotlin/templates/ObjectRuntime.kt#L31

type FfiObject struct {
	pointer      unsafe.Pointer
	callCounter  atomic.Int64
	freeFunction func(unsafe.Pointer, *C.RustCallStatus)
	destroyed    atomic.Bool
}

func newFfiObject(pointer unsafe.Pointer, freeFunction func(unsafe.Pointer, *C.RustCallStatus)) FfiObject {
	return FfiObject{
		pointer:      pointer,
		freeFunction: freeFunction,
	}
}

func (ffiObject *FfiObject) incrementPointer(debugName string) unsafe.Pointer {
	for {
		counter := ffiObject.callCounter.Load()
		if counter <= -1 {
			panic(fmt.Errorf("%v object has already been destroyed", debugName))
		}
		if counter == math.MaxInt64 {
			panic(fmt.Errorf("%v object call counter would overflow", debugName))
		}
		if ffiObject.callCounter.CompareAndSwap(counter, counter+1) {
			break
		}
	}

	return ffiObject.pointer
}

func (ffiObject *FfiObject) decrementPointer() {
	if ffiObject.callCounter.Add(-1) == -1 {
		ffiObject.freeRustArcPtr()
	}
}

func (ffiObject *FfiObject) destroy() {
	if ffiObject.destroyed.CompareAndSwap(false, true) {
		if ffiObject.callCounter.Add(-1) == -1 {
			ffiObject.freeRustArcPtr()
		}
	}
}

func (ffiObject *FfiObject) freeRustArcPtr() {
	rustCall(func(status *C.RustCallStatus) int32 {
		ffiObject.freeFunction(ffiObject.pointer, status)
		return 0
	})
}

type Builder struct {
	ffiObject FfiObject
}

func NewBuilder() *Builder {
	return FfiConverterBuilderINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) unsafe.Pointer {
		return C.uniffi_c2pa_fn_constructor_builder_new(_uniffiStatus)
	}))
}

func (_self *Builder) AddIngredient(ingredientJson string, format string, stream Stream) error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_add_ingredient(
			_pointer, FfiConverterStringINSTANCE.Lower(ingredientJson), FfiConverterStringINSTANCE.Lower(format), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) AddResource(uri string, stream Stream) error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_add_resource(
			_pointer, FfiConverterStringINSTANCE.Lower(uri), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) FromArchive(stream Stream) error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_from_archive(
			_pointer, FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) Sign(format string, input Stream, output Stream, signer *CallbackSigner) ([]byte, error) {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return C.uniffi_c2pa_fn_method_builder_sign(
			_pointer, FfiConverterStringINSTANCE.Lower(format), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(input), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(output), FfiConverterCallbackSignerINSTANCE.Lower(signer), _uniffiStatus)
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue []byte
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterBytesINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Builder) ToArchive(stream Stream) error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_to_archive(
			_pointer, FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) WithJson(json string) error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_with_json(
			_pointer, FfiConverterStringINSTANCE.Lower(json), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (object *Builder) Destroy() {
	runtime.SetFinalizer(object, nil)
	object.ffiObject.destroy()
}

type FfiConverterBuilder struct{}

var FfiConverterBuilderINSTANCE = FfiConverterBuilder{}

func (c FfiConverterBuilder) Lift(pointer unsafe.Pointer) *Builder {
	result := &Builder{
		newFfiObject(
			pointer,
			func(pointer unsafe.Pointer, status *C.RustCallStatus) {
				C.uniffi_c2pa_fn_free_builder(pointer, status)
			}),
	}
	runtime.SetFinalizer(result, (*Builder).Destroy)
	return result
}

func (c FfiConverterBuilder) Read(reader io.Reader) *Builder {
	return c.Lift(unsafe.Pointer(uintptr(readUint64(reader))))
}

func (c FfiConverterBuilder) Lower(value *Builder) unsafe.Pointer {
	// TODO: this is bad - all synchronization from ObjectRuntime.go is discarded here,
	// because the pointer will be decremented immediately after this function returns,
	// and someone will be left holding onto a non-locked pointer.
	pointer := value.ffiObject.incrementPointer("*Builder")
	defer value.ffiObject.decrementPointer()
	return pointer
}

func (c FfiConverterBuilder) Write(writer io.Writer, value *Builder) {
	writeUint64(writer, uint64(uintptr(c.Lower(value))))
}

type FfiDestroyerBuilder struct{}

func (_ FfiDestroyerBuilder) Destroy(value *Builder) {
	value.Destroy()
}

type CallbackSigner struct {
	ffiObject FfiObject
}

func NewCallbackSigner(callback SignerCallback, alg SigningAlg, certs []byte, taUrl *string) *CallbackSigner {
	return FfiConverterCallbackSignerINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) unsafe.Pointer {
		return C.uniffi_c2pa_fn_constructor_callbacksigner_new(FfiConverterCallbackInterfaceSignerCallbackINSTANCE.Lower(callback), FfiConverterTypeSigningAlgINSTANCE.Lower(alg), FfiConverterBytesINSTANCE.Lower(certs), FfiConverterOptionalStringINSTANCE.Lower(taUrl), _uniffiStatus)
	}))
}

func (object *CallbackSigner) Destroy() {
	runtime.SetFinalizer(object, nil)
	object.ffiObject.destroy()
}

type FfiConverterCallbackSigner struct{}

var FfiConverterCallbackSignerINSTANCE = FfiConverterCallbackSigner{}

func (c FfiConverterCallbackSigner) Lift(pointer unsafe.Pointer) *CallbackSigner {
	result := &CallbackSigner{
		newFfiObject(
			pointer,
			func(pointer unsafe.Pointer, status *C.RustCallStatus) {
				C.uniffi_c2pa_fn_free_callbacksigner(pointer, status)
			}),
	}
	runtime.SetFinalizer(result, (*CallbackSigner).Destroy)
	return result
}

func (c FfiConverterCallbackSigner) Read(reader io.Reader) *CallbackSigner {
	return c.Lift(unsafe.Pointer(uintptr(readUint64(reader))))
}

func (c FfiConverterCallbackSigner) Lower(value *CallbackSigner) unsafe.Pointer {
	// TODO: this is bad - all synchronization from ObjectRuntime.go is discarded here,
	// because the pointer will be decremented immediately after this function returns,
	// and someone will be left holding onto a non-locked pointer.
	pointer := value.ffiObject.incrementPointer("*CallbackSigner")
	defer value.ffiObject.decrementPointer()
	return pointer
}

func (c FfiConverterCallbackSigner) Write(writer io.Writer, value *CallbackSigner) {
	writeUint64(writer, uint64(uintptr(c.Lower(value))))
}

type FfiDestroyerCallbackSigner struct{}

func (_ FfiDestroyerCallbackSigner) Destroy(value *CallbackSigner) {
	value.Destroy()
}

type Reader struct {
	ffiObject FfiObject
}

func NewReader() *Reader {
	return FfiConverterReaderINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) unsafe.Pointer {
		return C.uniffi_c2pa_fn_constructor_reader_new(_uniffiStatus)
	}))
}

func (_self *Reader) FromStream(format string, reader Stream) (string, error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return C.uniffi_c2pa_fn_method_reader_from_stream(
			_pointer, FfiConverterStringINSTANCE.Lower(format), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(reader), _uniffiStatus)
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue string
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterStringINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Reader) Json() (string, error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return C.uniffi_c2pa_fn_method_reader_json(
			_pointer, _uniffiStatus)
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue string
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterStringINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Reader) ResourceToStream(uri string, stream Stream) (uint64, error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError(FfiConverterTypeError{}, func(_uniffiStatus *C.RustCallStatus) C.uint64_t {
		return C.uniffi_c2pa_fn_method_reader_resource_to_stream(
			_pointer, FfiConverterStringINSTANCE.Lower(uri), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue uint64
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterUint64INSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (object *Reader) Destroy() {
	runtime.SetFinalizer(object, nil)
	object.ffiObject.destroy()
}

type FfiConverterReader struct{}

var FfiConverterReaderINSTANCE = FfiConverterReader{}

func (c FfiConverterReader) Lift(pointer unsafe.Pointer) *Reader {
	result := &Reader{
		newFfiObject(
			pointer,
			func(pointer unsafe.Pointer, status *C.RustCallStatus) {
				C.uniffi_c2pa_fn_free_reader(pointer, status)
			}),
	}
	runtime.SetFinalizer(result, (*Reader).Destroy)
	return result
}

func (c FfiConverterReader) Read(reader io.Reader) *Reader {
	return c.Lift(unsafe.Pointer(uintptr(readUint64(reader))))
}

func (c FfiConverterReader) Lower(value *Reader) unsafe.Pointer {
	// TODO: this is bad - all synchronization from ObjectRuntime.go is discarded here,
	// because the pointer will be decremented immediately after this function returns,
	// and someone will be left holding onto a non-locked pointer.
	pointer := value.ffiObject.incrementPointer("*Reader")
	defer value.ffiObject.decrementPointer()
	return pointer
}

func (c FfiConverterReader) Write(writer io.Writer, value *Reader) {
	writeUint64(writer, uint64(uintptr(c.Lower(value))))
}

type FfiDestroyerReader struct{}

func (_ FfiDestroyerReader) Destroy(value *Reader) {
	value.Destroy()
}

type Error struct {
	err error
}

func (err Error) Error() string {
	return fmt.Sprintf("Error: %s", err.err.Error())
}

func (err Error) Unwrap() error {
	return err.err
}

// Err* are used for checking error type with `errors.Is`
var ErrErrorAssertion = fmt.Errorf("ErrorAssertion")
var ErrErrorAssertionNotFound = fmt.Errorf("ErrorAssertionNotFound")
var ErrErrorDecoding = fmt.Errorf("ErrorDecoding")
var ErrErrorEncoding = fmt.Errorf("ErrorEncoding")
var ErrErrorFileNotFound = fmt.Errorf("ErrorFileNotFound")
var ErrErrorIo = fmt.Errorf("ErrorIo")
var ErrErrorJson = fmt.Errorf("ErrorJson")
var ErrErrorManifest = fmt.Errorf("ErrorManifest")
var ErrErrorManifestNotFound = fmt.Errorf("ErrorManifestNotFound")
var ErrErrorNotSupported = fmt.Errorf("ErrorNotSupported")
var ErrErrorOther = fmt.Errorf("ErrorOther")
var ErrErrorRemoteManifest = fmt.Errorf("ErrorRemoteManifest")
var ErrErrorResourceNotFound = fmt.Errorf("ErrorResourceNotFound")
var ErrErrorRwLock = fmt.Errorf("ErrorRwLock")
var ErrErrorSignature = fmt.Errorf("ErrorSignature")
var ErrErrorVerify = fmt.Errorf("ErrorVerify")

// Variant structs
type ErrorAssertion struct {
	Reason string
}

func NewErrorAssertion(
	reason string,
) *Error {
	return &Error{
		err: &ErrorAssertion{
			Reason: reason,
		},
	}
}

func (err ErrorAssertion) Error() string {
	return fmt.Sprint("Assertion",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorAssertion) Is(target error) bool {
	return target == ErrErrorAssertion
}

type ErrorAssertionNotFound struct {
	Reason string
}

func NewErrorAssertionNotFound(
	reason string,
) *Error {
	return &Error{
		err: &ErrorAssertionNotFound{
			Reason: reason,
		},
	}
}

func (err ErrorAssertionNotFound) Error() string {
	return fmt.Sprint("AssertionNotFound",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorAssertionNotFound) Is(target error) bool {
	return target == ErrErrorAssertionNotFound
}

type ErrorDecoding struct {
	Reason string
}

func NewErrorDecoding(
	reason string,
) *Error {
	return &Error{
		err: &ErrorDecoding{
			Reason: reason,
		},
	}
}

func (err ErrorDecoding) Error() string {
	return fmt.Sprint("Decoding",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorDecoding) Is(target error) bool {
	return target == ErrErrorDecoding
}

type ErrorEncoding struct {
	Reason string
}

func NewErrorEncoding(
	reason string,
) *Error {
	return &Error{
		err: &ErrorEncoding{
			Reason: reason,
		},
	}
}

func (err ErrorEncoding) Error() string {
	return fmt.Sprint("Encoding",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorEncoding) Is(target error) bool {
	return target == ErrErrorEncoding
}

type ErrorFileNotFound struct {
	Reason string
}

func NewErrorFileNotFound(
	reason string,
) *Error {
	return &Error{
		err: &ErrorFileNotFound{
			Reason: reason,
		},
	}
}

func (err ErrorFileNotFound) Error() string {
	return fmt.Sprint("FileNotFound",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorFileNotFound) Is(target error) bool {
	return target == ErrErrorFileNotFound
}

type ErrorIo struct {
	Reason string
}

func NewErrorIo(
	reason string,
) *Error {
	return &Error{
		err: &ErrorIo{
			Reason: reason,
		},
	}
}

func (err ErrorIo) Error() string {
	return fmt.Sprint("Io",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorIo) Is(target error) bool {
	return target == ErrErrorIo
}

type ErrorJson struct {
	Reason string
}

func NewErrorJson(
	reason string,
) *Error {
	return &Error{
		err: &ErrorJson{
			Reason: reason,
		},
	}
}

func (err ErrorJson) Error() string {
	return fmt.Sprint("Json",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorJson) Is(target error) bool {
	return target == ErrErrorJson
}

type ErrorManifest struct {
	Reason string
}

func NewErrorManifest(
	reason string,
) *Error {
	return &Error{
		err: &ErrorManifest{
			Reason: reason,
		},
	}
}

func (err ErrorManifest) Error() string {
	return fmt.Sprint("Manifest",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorManifest) Is(target error) bool {
	return target == ErrErrorManifest
}

type ErrorManifestNotFound struct {
	Reason string
}

func NewErrorManifestNotFound(
	reason string,
) *Error {
	return &Error{
		err: &ErrorManifestNotFound{
			Reason: reason,
		},
	}
}

func (err ErrorManifestNotFound) Error() string {
	return fmt.Sprint("ManifestNotFound",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorManifestNotFound) Is(target error) bool {
	return target == ErrErrorManifestNotFound
}

type ErrorNotSupported struct {
	Reason string
}

func NewErrorNotSupported(
	reason string,
) *Error {
	return &Error{
		err: &ErrorNotSupported{
			Reason: reason,
		},
	}
}

func (err ErrorNotSupported) Error() string {
	return fmt.Sprint("NotSupported",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorNotSupported) Is(target error) bool {
	return target == ErrErrorNotSupported
}

type ErrorOther struct {
	Reason string
}

func NewErrorOther(
	reason string,
) *Error {
	return &Error{
		err: &ErrorOther{
			Reason: reason,
		},
	}
}

func (err ErrorOther) Error() string {
	return fmt.Sprint("Other",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorOther) Is(target error) bool {
	return target == ErrErrorOther
}

type ErrorRemoteManifest struct {
	Reason string
}

func NewErrorRemoteManifest(
	reason string,
) *Error {
	return &Error{
		err: &ErrorRemoteManifest{
			Reason: reason,
		},
	}
}

func (err ErrorRemoteManifest) Error() string {
	return fmt.Sprint("RemoteManifest",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorRemoteManifest) Is(target error) bool {
	return target == ErrErrorRemoteManifest
}

type ErrorResourceNotFound struct {
	Reason string
}

func NewErrorResourceNotFound(
	reason string,
) *Error {
	return &Error{
		err: &ErrorResourceNotFound{
			Reason: reason,
		},
	}
}

func (err ErrorResourceNotFound) Error() string {
	return fmt.Sprint("ResourceNotFound",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorResourceNotFound) Is(target error) bool {
	return target == ErrErrorResourceNotFound
}

type ErrorRwLock struct {
}

func NewErrorRwLock() *Error {
	return &Error{
		err: &ErrorRwLock{},
	}
}

func (err ErrorRwLock) Error() string {
	return fmt.Sprint("RwLock")
}

func (self ErrorRwLock) Is(target error) bool {
	return target == ErrErrorRwLock
}

type ErrorSignature struct {
	Reason string
}

func NewErrorSignature(
	reason string,
) *Error {
	return &Error{
		err: &ErrorSignature{
			Reason: reason,
		},
	}
}

func (err ErrorSignature) Error() string {
	return fmt.Sprint("Signature",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorSignature) Is(target error) bool {
	return target == ErrErrorSignature
}

type ErrorVerify struct {
	Reason string
}

func NewErrorVerify(
	reason string,
) *Error {
	return &Error{
		err: &ErrorVerify{
			Reason: reason,
		},
	}
}

func (err ErrorVerify) Error() string {
	return fmt.Sprint("Verify",
		": ",

		"Reason=",
		err.Reason,
	)
}

func (self ErrorVerify) Is(target error) bool {
	return target == ErrErrorVerify
}

type FfiConverterTypeError struct{}

var FfiConverterTypeErrorINSTANCE = FfiConverterTypeError{}

func (c FfiConverterTypeError) Lift(eb RustBufferI) error {
	return LiftFromRustBuffer[error](c, eb)
}

func (c FfiConverterTypeError) Lower(value *Error) RustBuffer {
	return LowerIntoRustBuffer[*Error](c, value)
}

func (c FfiConverterTypeError) Read(reader io.Reader) error {
	errorID := readUint32(reader)

	switch errorID {
	case 1:
		return &Error{&ErrorAssertion{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 2:
		return &Error{&ErrorAssertionNotFound{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 3:
		return &Error{&ErrorDecoding{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 4:
		return &Error{&ErrorEncoding{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 5:
		return &Error{&ErrorFileNotFound{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 6:
		return &Error{&ErrorIo{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 7:
		return &Error{&ErrorJson{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 8:
		return &Error{&ErrorManifest{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 9:
		return &Error{&ErrorManifestNotFound{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 10:
		return &Error{&ErrorNotSupported{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 11:
		return &Error{&ErrorOther{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 12:
		return &Error{&ErrorRemoteManifest{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 13:
		return &Error{&ErrorResourceNotFound{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 14:
		return &Error{&ErrorRwLock{}}
	case 15:
		return &Error{&ErrorSignature{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	case 16:
		return &Error{&ErrorVerify{
			Reason: FfiConverterStringINSTANCE.Read(reader),
		}}
	default:
		panic(fmt.Sprintf("Unknown error code %d in FfiConverterTypeError.Read()", errorID))
	}
}

func (c FfiConverterTypeError) Write(writer io.Writer, value *Error) {
	switch variantValue := value.err.(type) {
	case *ErrorAssertion:
		writeInt32(writer, 1)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorAssertionNotFound:
		writeInt32(writer, 2)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorDecoding:
		writeInt32(writer, 3)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorEncoding:
		writeInt32(writer, 4)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorFileNotFound:
		writeInt32(writer, 5)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorIo:
		writeInt32(writer, 6)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorJson:
		writeInt32(writer, 7)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorManifest:
		writeInt32(writer, 8)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorManifestNotFound:
		writeInt32(writer, 9)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorNotSupported:
		writeInt32(writer, 10)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorOther:
		writeInt32(writer, 11)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorRemoteManifest:
		writeInt32(writer, 12)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorResourceNotFound:
		writeInt32(writer, 13)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorRwLock:
		writeInt32(writer, 14)
	case *ErrorSignature:
		writeInt32(writer, 15)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	case *ErrorVerify:
		writeInt32(writer, 16)
		FfiConverterStringINSTANCE.Write(writer, variantValue.Reason)
	default:
		_ = variantValue
		panic(fmt.Sprintf("invalid error value `%v` in FfiConverterTypeError.Write", value))
	}
}

type SeekMode uint

const (
	SeekModeStart   SeekMode = 1
	SeekModeEnd     SeekMode = 2
	SeekModeCurrent SeekMode = 3
)

type FfiConverterTypeSeekMode struct{}

var FfiConverterTypeSeekModeINSTANCE = FfiConverterTypeSeekMode{}

func (c FfiConverterTypeSeekMode) Lift(rb RustBufferI) SeekMode {
	return LiftFromRustBuffer[SeekMode](c, rb)
}

func (c FfiConverterTypeSeekMode) Lower(value SeekMode) RustBuffer {
	return LowerIntoRustBuffer[SeekMode](c, value)
}
func (FfiConverterTypeSeekMode) Read(reader io.Reader) SeekMode {
	id := readInt32(reader)
	return SeekMode(id)
}

func (FfiConverterTypeSeekMode) Write(writer io.Writer, value SeekMode) {
	writeInt32(writer, int32(value))
}

type FfiDestroyerTypeSeekMode struct{}

func (_ FfiDestroyerTypeSeekMode) Destroy(value SeekMode) {
}

type SigningAlg uint

const (
	SigningAlgEs256   SigningAlg = 1
	SigningAlgEs384   SigningAlg = 2
	SigningAlgEs512   SigningAlg = 3
	SigningAlgPs256   SigningAlg = 4
	SigningAlgPs384   SigningAlg = 5
	SigningAlgPs512   SigningAlg = 6
	SigningAlgEd25519 SigningAlg = 7
)

type FfiConverterTypeSigningAlg struct{}

var FfiConverterTypeSigningAlgINSTANCE = FfiConverterTypeSigningAlg{}

func (c FfiConverterTypeSigningAlg) Lift(rb RustBufferI) SigningAlg {
	return LiftFromRustBuffer[SigningAlg](c, rb)
}

func (c FfiConverterTypeSigningAlg) Lower(value SigningAlg) RustBuffer {
	return LowerIntoRustBuffer[SigningAlg](c, value)
}
func (FfiConverterTypeSigningAlg) Read(reader io.Reader) SigningAlg {
	id := readInt32(reader)
	return SigningAlg(id)
}

func (FfiConverterTypeSigningAlg) Write(writer io.Writer, value SigningAlg) {
	writeInt32(writer, int32(value))
}

type FfiDestroyerTypeSigningAlg struct{}

func (_ FfiDestroyerTypeSigningAlg) Destroy(value SigningAlg) {
}

type uniffiCallbackResult C.int32_t

const (
	uniffiIdxCallbackFree               uniffiCallbackResult = 0
	uniffiCallbackResultSuccess         uniffiCallbackResult = 0
	uniffiCallbackResultError           uniffiCallbackResult = 1
	uniffiCallbackUnexpectedResultError uniffiCallbackResult = 2
	uniffiCallbackCancelled             uniffiCallbackResult = 3
)

type concurrentHandleMap[T any] struct {
	leftMap       map[uint64]*T
	rightMap      map[*T]uint64
	currentHandle uint64
	lock          sync.RWMutex
}

func newConcurrentHandleMap[T any]() *concurrentHandleMap[T] {
	return &concurrentHandleMap[T]{
		leftMap:  map[uint64]*T{},
		rightMap: map[*T]uint64{},
	}
}

func (cm *concurrentHandleMap[T]) insert(obj *T) uint64 {
	cm.lock.Lock()
	defer cm.lock.Unlock()

	if existingHandle, ok := cm.rightMap[obj]; ok {
		return existingHandle
	}
	cm.currentHandle = cm.currentHandle + 1
	cm.leftMap[cm.currentHandle] = obj
	cm.rightMap[obj] = cm.currentHandle
	return cm.currentHandle
}

func (cm *concurrentHandleMap[T]) remove(handle uint64) bool {
	cm.lock.Lock()
	defer cm.lock.Unlock()

	if val, ok := cm.leftMap[handle]; ok {
		delete(cm.leftMap, handle)
		delete(cm.rightMap, val)
	}
	return false
}

func (cm *concurrentHandleMap[T]) tryGet(handle uint64) (*T, bool) {
	cm.lock.RLock()
	defer cm.lock.RUnlock()

	val, ok := cm.leftMap[handle]
	return val, ok
}

type FfiConverterCallbackInterface[CallbackInterface any] struct {
	handleMap *concurrentHandleMap[CallbackInterface]
}

func (c *FfiConverterCallbackInterface[CallbackInterface]) drop(handle uint64) RustBuffer {
	c.handleMap.remove(handle)
	return RustBuffer{}
}

func (c *FfiConverterCallbackInterface[CallbackInterface]) Lift(handle uint64) CallbackInterface {
	val, ok := c.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}
	return *val
}

func (c *FfiConverterCallbackInterface[CallbackInterface]) Read(reader io.Reader) CallbackInterface {
	return c.Lift(readUint64(reader))
}

func (c *FfiConverterCallbackInterface[CallbackInterface]) Lower(value CallbackInterface) C.uint64_t {
	return C.uint64_t(c.handleMap.insert(&value))
}

func (c *FfiConverterCallbackInterface[CallbackInterface]) Write(writer io.Writer, value CallbackInterface) {
	writeUint64(writer, uint64(c.Lower(value)))
}

type SignerCallback interface {
	Sign(data []byte) ([]byte, *Error)
}

// foreignCallbackCallbackInterfaceSignerCallback cannot be callable be a compiled function at a same time
type foreignCallbackCallbackInterfaceSignerCallback struct{}

//export c2pa_cgo_SignerCallback
func c2pa_cgo_SignerCallback(handle C.uint64_t, method C.int32_t, argsPtr *C.uint8_t, argsLen C.int32_t, outBuf *C.RustBuffer) C.int32_t {
	cb := FfiConverterCallbackInterfaceSignerCallbackINSTANCE.Lift(uint64(handle))
	switch method {
	case 0:
		// 0 means Rust is done with the callback, and the callback
		// can be dropped by the foreign language.
		*outBuf = FfiConverterCallbackInterfaceSignerCallbackINSTANCE.drop(uint64(handle))
		// See docs of ForeignCallback in `uniffi/src/ffi/foreigncallbacks.rs`
		return C.int32_t(uniffiIdxCallbackFree)

	case 1:
		var result uniffiCallbackResult
		args := unsafe.Slice((*byte)(argsPtr), argsLen)
		result = foreignCallbackCallbackInterfaceSignerCallback{}.InvokeSign(cb, args, outBuf)
		return C.int32_t(result)

	default:
		// This should never happen, because an out of bounds method index won't
		// ever be used. Once we can catch errors, we should return an InternalException.
		// https://github.com/mozilla/uniffi-rs/issues/351
		return C.int32_t(uniffiCallbackUnexpectedResultError)
	}
}

func (foreignCallbackCallbackInterfaceSignerCallback) InvokeSign(callback SignerCallback, args []byte, outBuf *C.RustBuffer) uniffiCallbackResult {
	reader := bytes.NewReader(args)
	result, err := callback.Sign(FfiConverterBytesINSTANCE.Read(reader))

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			return uniffiCallbackUnexpectedResultError
		}
		*outBuf = LowerIntoRustBuffer[*Error](FfiConverterTypeErrorINSTANCE, err)
		return uniffiCallbackResultError
	}
	*outBuf = LowerIntoRustBuffer[[]byte](FfiConverterBytesINSTANCE, result)
	return uniffiCallbackResultSuccess
}

type FfiConverterCallbackInterfaceSignerCallback struct {
	FfiConverterCallbackInterface[SignerCallback]
}

var FfiConverterCallbackInterfaceSignerCallbackINSTANCE = &FfiConverterCallbackInterfaceSignerCallback{
	FfiConverterCallbackInterface: FfiConverterCallbackInterface[SignerCallback]{
		handleMap: newConcurrentHandleMap[SignerCallback](),
	},
}

// This is a static function because only 1 instance is supported for registering
func (c *FfiConverterCallbackInterfaceSignerCallback) register() {
	rustCall(func(status *C.RustCallStatus) int32 {
		C.uniffi_c2pa_fn_init_callback_signercallback(C.ForeignCallback(C.c2pa_cgo_SignerCallback), status)
		return 0
	})
}

type FfiDestroyerCallbackInterfaceSignerCallback struct{}

func (FfiDestroyerCallbackInterfaceSignerCallback) Destroy(value SignerCallback) {
}

type Stream interface {
	ReadStream(length uint64) ([]byte, *Error)

	SeekStream(pos int64, mode SeekMode) (uint64, *Error)

	WriteStream(data []byte) (uint64, *Error)
}

// foreignCallbackCallbackInterfaceStream cannot be callable be a compiled function at a same time
type foreignCallbackCallbackInterfaceStream struct{}

//export c2pa_cgo_Stream
func c2pa_cgo_Stream(handle C.uint64_t, method C.int32_t, argsPtr *C.uint8_t, argsLen C.int32_t, outBuf *C.RustBuffer) C.int32_t {
	cb := FfiConverterCallbackInterfaceStreamINSTANCE.Lift(uint64(handle))
	switch method {
	case 0:
		// 0 means Rust is done with the callback, and the callback
		// can be dropped by the foreign language.
		*outBuf = FfiConverterCallbackInterfaceStreamINSTANCE.drop(uint64(handle))
		// See docs of ForeignCallback in `uniffi/src/ffi/foreigncallbacks.rs`
		return C.int32_t(uniffiIdxCallbackFree)

	case 1:
		var result uniffiCallbackResult
		args := unsafe.Slice((*byte)(argsPtr), argsLen)
		result = foreignCallbackCallbackInterfaceStream{}.InvokeReadStream(cb, args, outBuf)
		return C.int32_t(result)
	case 2:
		var result uniffiCallbackResult
		args := unsafe.Slice((*byte)(argsPtr), argsLen)
		result = foreignCallbackCallbackInterfaceStream{}.InvokeSeekStream(cb, args, outBuf)
		return C.int32_t(result)
	case 3:
		var result uniffiCallbackResult
		args := unsafe.Slice((*byte)(argsPtr), argsLen)
		result = foreignCallbackCallbackInterfaceStream{}.InvokeWriteStream(cb, args, outBuf)
		return C.int32_t(result)

	default:
		// This should never happen, because an out of bounds method index won't
		// ever be used. Once we can catch errors, we should return an InternalException.
		// https://github.com/mozilla/uniffi-rs/issues/351
		return C.int32_t(uniffiCallbackUnexpectedResultError)
	}
}

func (foreignCallbackCallbackInterfaceStream) InvokeReadStream(callback Stream, args []byte, outBuf *C.RustBuffer) uniffiCallbackResult {
	reader := bytes.NewReader(args)
	result, err := callback.ReadStream(FfiConverterUint64INSTANCE.Read(reader))

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			return uniffiCallbackUnexpectedResultError
		}
		*outBuf = LowerIntoRustBuffer[*Error](FfiConverterTypeErrorINSTANCE, err)
		return uniffiCallbackResultError
	}
	*outBuf = LowerIntoRustBuffer[[]byte](FfiConverterBytesINSTANCE, result)
	return uniffiCallbackResultSuccess
}
func (foreignCallbackCallbackInterfaceStream) InvokeSeekStream(callback Stream, args []byte, outBuf *C.RustBuffer) uniffiCallbackResult {
	reader := bytes.NewReader(args)
	result, err := callback.SeekStream(FfiConverterInt64INSTANCE.Read(reader), FfiConverterTypeSeekModeINSTANCE.Read(reader))

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			return uniffiCallbackUnexpectedResultError
		}
		*outBuf = LowerIntoRustBuffer[*Error](FfiConverterTypeErrorINSTANCE, err)
		return uniffiCallbackResultError
	}
	*outBuf = LowerIntoRustBuffer[uint64](FfiConverterUint64INSTANCE, result)
	return uniffiCallbackResultSuccess
}
func (foreignCallbackCallbackInterfaceStream) InvokeWriteStream(callback Stream, args []byte, outBuf *C.RustBuffer) uniffiCallbackResult {
	reader := bytes.NewReader(args)
	result, err := callback.WriteStream(FfiConverterBytesINSTANCE.Read(reader))

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			return uniffiCallbackUnexpectedResultError
		}
		*outBuf = LowerIntoRustBuffer[*Error](FfiConverterTypeErrorINSTANCE, err)
		return uniffiCallbackResultError
	}
	*outBuf = LowerIntoRustBuffer[uint64](FfiConverterUint64INSTANCE, result)
	return uniffiCallbackResultSuccess
}

type FfiConverterCallbackInterfaceStream struct {
	FfiConverterCallbackInterface[Stream]
}

var FfiConverterCallbackInterfaceStreamINSTANCE = &FfiConverterCallbackInterfaceStream{
	FfiConverterCallbackInterface: FfiConverterCallbackInterface[Stream]{
		handleMap: newConcurrentHandleMap[Stream](),
	},
}

// This is a static function because only 1 instance is supported for registering
func (c *FfiConverterCallbackInterfaceStream) register() {
	rustCall(func(status *C.RustCallStatus) int32 {
		C.uniffi_c2pa_fn_init_callback_stream(C.ForeignCallback(C.c2pa_cgo_Stream), status)
		return 0
	})
}

type FfiDestroyerCallbackInterfaceStream struct{}

func (FfiDestroyerCallbackInterfaceStream) Destroy(value Stream) {
}

type FfiConverterOptionalString struct{}

var FfiConverterOptionalStringINSTANCE = FfiConverterOptionalString{}

func (c FfiConverterOptionalString) Lift(rb RustBufferI) *string {
	return LiftFromRustBuffer[*string](c, rb)
}

func (_ FfiConverterOptionalString) Read(reader io.Reader) *string {
	if readInt8(reader) == 0 {
		return nil
	}
	temp := FfiConverterStringINSTANCE.Read(reader)
	return &temp
}

func (c FfiConverterOptionalString) Lower(value *string) RustBuffer {
	return LowerIntoRustBuffer[*string](c, value)
}

func (_ FfiConverterOptionalString) Write(writer io.Writer, value *string) {
	if value == nil {
		writeInt8(writer, 0)
	} else {
		writeInt8(writer, 1)
		FfiConverterStringINSTANCE.Write(writer, *value)
	}
}

type FfiDestroyerOptionalString struct{}

func (_ FfiDestroyerOptionalString) Destroy(value *string) {
	if value != nil {
		FfiDestroyerString{}.Destroy(*value)
	}
}

func SdkVersion() string {
	return FfiConverterStringINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return C.uniffi_c2pa_fn_func_sdk_version(_uniffiStatus)
	}))
}

func Version() string {
	return FfiConverterStringINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return C.uniffi_c2pa_fn_func_version(_uniffiStatus)
	}))
}
