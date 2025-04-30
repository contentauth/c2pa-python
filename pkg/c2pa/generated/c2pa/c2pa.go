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

// This is needed, because as of go 1.24
// type RustBuffer C.RustBuffer cannot have methods,
// RustBuffer is treated as non-local type
type GoRustBuffer struct {
	inner C.RustBuffer
}

type RustBufferI interface {
	AsReader() *bytes.Reader
	Free()
	ToGoBytes() []byte
	Data() unsafe.Pointer
	Len() uint64
	Capacity() uint64
}

func RustBufferFromExternal(b RustBufferI) GoRustBuffer {
	return GoRustBuffer{
		inner: C.RustBuffer{
			capacity: C.uint64_t(b.Capacity()),
			len:      C.uint64_t(b.Len()),
			data:     (*C.uchar)(b.Data()),
		},
	}
}

func (cb GoRustBuffer) Capacity() uint64 {
	return uint64(cb.inner.capacity)
}

func (cb GoRustBuffer) Len() uint64 {
	return uint64(cb.inner.len)
}

func (cb GoRustBuffer) Data() unsafe.Pointer {
	return unsafe.Pointer(cb.inner.data)
}

func (cb GoRustBuffer) AsReader() *bytes.Reader {
	b := unsafe.Slice((*byte)(cb.inner.data), C.uint64_t(cb.inner.len))
	return bytes.NewReader(b)
}

func (cb GoRustBuffer) Free() {
	rustCall(func(status *C.RustCallStatus) bool {
		C.ffi_c2pa_rustbuffer_free(cb.inner, status)
		return false
	})
}

func (cb GoRustBuffer) ToGoBytes() []byte {
	return C.GoBytes(unsafe.Pointer(cb.inner.data), C.int(cb.inner.len))
}

func stringToRustBuffer(str string) C.RustBuffer {
	return bytesToRustBuffer([]byte(str))
}

func bytesToRustBuffer(b []byte) C.RustBuffer {
	if len(b) == 0 {
		return C.RustBuffer{}
	}
	// We can pass the pointer along here, as it is pinned
	// for the duration of this call
	foreign := C.ForeignBytes{
		len:  C.int(len(b)),
		data: (*C.uchar)(unsafe.Pointer(&b[0])),
	}

	return rustCall(func(status *C.RustCallStatus) C.RustBuffer {
		return C.ffi_c2pa_rustbuffer_from_bytes(foreign, status)
	})
}

type BufLifter[GoType any] interface {
	Lift(value RustBufferI) GoType
}

type BufLowerer[GoType any] interface {
	Lower(value GoType) C.RustBuffer
}

type BufReader[GoType any] interface {
	Read(reader io.Reader) GoType
}

type BufWriter[GoType any] interface {
	Write(writer io.Writer, value GoType)
}

func LowerIntoRustBuffer[GoType any](bufWriter BufWriter[GoType], value GoType) C.RustBuffer {
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

func rustCallWithError[E any, U any](converter BufReader[*E], callback func(*C.RustCallStatus) U) (U, *E) {
	var status C.RustCallStatus
	returnValue := callback(&status)
	err := checkCallStatus(converter, status)
	return returnValue, err
}

func checkCallStatus[E any](converter BufReader[*E], status C.RustCallStatus) *E {
	switch status.code {
	case 0:
		return nil
	case 1:
		return LiftFromRustBuffer(converter, GoRustBuffer{inner: status.errorBuf})
	case 2:
		// when the rust code sees a panic, it tries to construct a rustBuffer
		// with the message.  but if that code panics, then it just sends back
		// an empty buffer.
		if status.errorBuf.len > 0 {
			panic(fmt.Errorf("%s", FfiConverterStringINSTANCE.Lift(GoRustBuffer{inner: status.errorBuf})))
		} else {
			panic(fmt.Errorf("Rust panicked while handling Rust panic"))
		}
	default:
		panic(fmt.Errorf("unknown status code: %d", status.code))
	}
}

func checkCallStatusUnknown(status C.RustCallStatus) error {
	switch status.code {
	case 0:
		return nil
	case 1:
		panic(fmt.Errorf("function not returning an error returned an error"))
	case 2:
		// when the rust code sees a panic, it tries to construct a C.RustBuffer
		// with the message.  but if that code panics, then it just sends back
		// an empty buffer.
		if status.errorBuf.len > 0 {
			panic(fmt.Errorf("%s", FfiConverterStringINSTANCE.Lift(GoRustBuffer{
				inner: status.errorBuf,
			})))
		} else {
			panic(fmt.Errorf("Rust panicked while handling Rust panic"))
		}
	default:
		return fmt.Errorf("unknown status code: %d", status.code)
	}
}

func rustCall[U any](callback func(*C.RustCallStatus) U) U {
	returnValue, err := rustCallWithError[error](nil, callback)
	if err != nil {
		panic(err)
	}
	return returnValue
}

type NativeError interface {
	AsError() error
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

	FfiConverterCallbackInterfaceSignerCallbackINSTANCE.register()
	FfiConverterCallbackInterfaceStreamINSTANCE.register()
	uniffiCheckChecksums()
}

func uniffiCheckChecksums() {
	// Get the bindings contract version from our ComponentInterface
	bindingsContractVersion := 26
	// Get the scaffolding contract version by calling the into the dylib
	scaffoldingContractVersion := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint32_t {
		return C.ffi_c2pa_uniffi_contract_version()
	})
	if bindingsContractVersion != int(scaffoldingContractVersion) {
		// If this happens try cleaning and rebuilding your project
		panic("c2pa: UniFFI contract version mismatch")
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_func_sdk_version()
		})
		if checksum != 37245 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_func_sdk_version: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_func_version()
		})
		if checksum != 61576 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_func_version: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_add_ingredient()
		})
		if checksum != 56163 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_add_ingredient: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_add_resource()
		})
		if checksum != 52123 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_add_resource: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_from_archive()
		})
		if checksum != 45068 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_from_archive: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_sign()
		})
		if checksum != 31394 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_sign: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_to_archive()
		})
		if checksum != 56076 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_to_archive: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_builder_with_json()
		})
		if checksum != 60973 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_builder_with_json: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_from_stream()
		})
		if checksum != 62816 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_from_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_get_provenance_cert_chain()
		})
		if checksum != 22683 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_get_provenance_cert_chain: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_json()
		})
		if checksum != 25079 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_json: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_reader_resource_to_stream()
		})
		if checksum != 32633 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_reader_resource_to_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_constructor_builder_new()
		})
		if checksum != 43948 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_constructor_builder_new: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_constructor_callbacksigner_new()
		})
		if checksum != 65452 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_constructor_callbacksigner_new: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_constructor_reader_new()
		})
		if checksum != 19939 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_constructor_reader_new: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_signercallback_sign()
		})
		if checksum != 64776 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_signercallback_sign: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_stream_read_stream()
		})
		if checksum != 16779 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_stream_read_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_stream_seek_stream()
		})
		if checksum != 39220 {
			// If this happens try cleaning and rebuilding your project
			panic("c2pa: uniffi_c2pa_checksum_method_stream_seek_stream: UniFFI API checksum mismatch")
		}
	}
	{
		checksum := rustCall(func(_uniffiStatus *C.RustCallStatus) C.uint16_t {
			return C.uniffi_c2pa_checksum_method_stream_write_stream()
		})
		if checksum != 63217 {
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

func (FfiConverterString) Lower(value string) C.RustBuffer {
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

func (c FfiConverterBytes) Lower(value []byte) C.RustBuffer {
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
	pointer       unsafe.Pointer
	callCounter   atomic.Int64
	cloneFunction func(unsafe.Pointer, *C.RustCallStatus) unsafe.Pointer
	freeFunction  func(unsafe.Pointer, *C.RustCallStatus)
	destroyed     atomic.Bool
}

func newFfiObject(
	pointer unsafe.Pointer,
	cloneFunction func(unsafe.Pointer, *C.RustCallStatus) unsafe.Pointer,
	freeFunction func(unsafe.Pointer, *C.RustCallStatus),
) FfiObject {
	return FfiObject{
		pointer:       pointer,
		cloneFunction: cloneFunction,
		freeFunction:  freeFunction,
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

	return rustCall(func(status *C.RustCallStatus) unsafe.Pointer {
		return ffiObject.cloneFunction(ffiObject.pointer, status)
	})
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

type BuilderInterface interface {
	AddIngredient(ingredientJson string, format string, stream Stream) *Error
	AddResource(uri string, stream Stream) *Error
	FromArchive(stream Stream) *Error
	Sign(format string, input Stream, output Stream, signer *CallbackSigner) ([]byte, *Error)
	ToArchive(stream Stream) *Error
	WithJson(json string) *Error
}
type Builder struct {
	ffiObject FfiObject
}

func NewBuilder() *Builder {
	return FfiConverterBuilderINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) unsafe.Pointer {
		return C.uniffi_c2pa_fn_constructor_builder_new(_uniffiStatus)
	}))
}

func (_self *Builder) AddIngredient(ingredientJson string, format string, stream Stream) *Error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_add_ingredient(
			_pointer, FfiConverterStringINSTANCE.Lower(ingredientJson), FfiConverterStringINSTANCE.Lower(format), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) AddResource(uri string, stream Stream) *Error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_add_resource(
			_pointer, FfiConverterStringINSTANCE.Lower(uri), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) FromArchive(stream Stream) *Error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_from_archive(
			_pointer, FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) Sign(format string, input Stream, output Stream, signer *CallbackSigner) ([]byte, *Error) {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return GoRustBuffer{
			inner: C.uniffi_c2pa_fn_method_builder_sign(
				_pointer, FfiConverterStringINSTANCE.Lower(format), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(input), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(output), FfiConverterCallbackSignerINSTANCE.Lower(signer), _uniffiStatus),
		}
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue []byte
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterBytesINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Builder) ToArchive(stream Stream) *Error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) bool {
		C.uniffi_c2pa_fn_method_builder_to_archive(
			_pointer, FfiConverterCallbackInterfaceStreamINSTANCE.Lower(stream), _uniffiStatus)
		return false
	})
	return _uniffiErr
}

func (_self *Builder) WithJson(json string) *Error {
	_pointer := _self.ffiObject.incrementPointer("*Builder")
	defer _self.ffiObject.decrementPointer()
	_, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) bool {
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
			func(pointer unsafe.Pointer, status *C.RustCallStatus) unsafe.Pointer {
				return C.uniffi_c2pa_fn_clone_builder(pointer, status)
			},
			func(pointer unsafe.Pointer, status *C.RustCallStatus) {
				C.uniffi_c2pa_fn_free_builder(pointer, status)
			},
		),
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

type CallbackSignerInterface interface {
}
type CallbackSigner struct {
	ffiObject FfiObject
}

func NewCallbackSigner(callback SignerCallback, alg SigningAlg, certs []byte, taUrl *string) *CallbackSigner {
	return FfiConverterCallbackSignerINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) unsafe.Pointer {
		return C.uniffi_c2pa_fn_constructor_callbacksigner_new(FfiConverterCallbackInterfaceSignerCallbackINSTANCE.Lower(callback), FfiConverterSigningAlgINSTANCE.Lower(alg), FfiConverterBytesINSTANCE.Lower(certs), FfiConverterOptionalStringINSTANCE.Lower(taUrl), _uniffiStatus)
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
			func(pointer unsafe.Pointer, status *C.RustCallStatus) unsafe.Pointer {
				return C.uniffi_c2pa_fn_clone_callbacksigner(pointer, status)
			},
			func(pointer unsafe.Pointer, status *C.RustCallStatus) {
				C.uniffi_c2pa_fn_free_callbacksigner(pointer, status)
			},
		),
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

type ReaderInterface interface {
	FromStream(format string, reader Stream) (string, *Error)
	GetProvenanceCertChain() (string, *Error)
	Json() (string, *Error)
	ResourceToStream(uri string, stream Stream) (uint64, *Error)
}
type Reader struct {
	ffiObject FfiObject
}

func NewReader() *Reader {
	return FfiConverterReaderINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) unsafe.Pointer {
		return C.uniffi_c2pa_fn_constructor_reader_new(_uniffiStatus)
	}))
}

func (_self *Reader) FromStream(format string, reader Stream) (string, *Error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return GoRustBuffer{
			inner: C.uniffi_c2pa_fn_method_reader_from_stream(
				_pointer, FfiConverterStringINSTANCE.Lower(format), FfiConverterCallbackInterfaceStreamINSTANCE.Lower(reader), _uniffiStatus),
		}
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue string
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterStringINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Reader) GetProvenanceCertChain() (string, *Error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return GoRustBuffer{
			inner: C.uniffi_c2pa_fn_method_reader_get_provenance_cert_chain(
				_pointer, _uniffiStatus),
		}
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue string
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterStringINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Reader) Json() (string, *Error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return GoRustBuffer{
			inner: C.uniffi_c2pa_fn_method_reader_json(
				_pointer, _uniffiStatus),
		}
	})
	if _uniffiErr != nil {
		var _uniffiDefaultValue string
		return _uniffiDefaultValue, _uniffiErr
	} else {
		return FfiConverterStringINSTANCE.Lift(_uniffiRV), _uniffiErr
	}
}

func (_self *Reader) ResourceToStream(uri string, stream Stream) (uint64, *Error) {
	_pointer := _self.ffiObject.incrementPointer("*Reader")
	defer _self.ffiObject.decrementPointer()
	_uniffiRV, _uniffiErr := rustCallWithError[Error](FfiConverterError{}, func(_uniffiStatus *C.RustCallStatus) C.uint64_t {
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
			func(pointer unsafe.Pointer, status *C.RustCallStatus) unsafe.Pointer {
				return C.uniffi_c2pa_fn_clone_reader(pointer, status)
			},
			func(pointer unsafe.Pointer, status *C.RustCallStatus) {
				C.uniffi_c2pa_fn_free_reader(pointer, status)
			},
		),
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

// Convience method to turn *Error into error
// Avoiding treating nil pointer as non nil error interface
func (err *Error) AsError() error {
	if err == nil {
		return nil
	} else {
		return err
	}
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
	return &Error{err: &ErrorAssertion{
		Reason: reason}}
}

func (e ErrorAssertion) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorAssertionNotFound{
		Reason: reason}}
}

func (e ErrorAssertionNotFound) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorDecoding{
		Reason: reason}}
}

func (e ErrorDecoding) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorEncoding{
		Reason: reason}}
}

func (e ErrorEncoding) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorFileNotFound{
		Reason: reason}}
}

func (e ErrorFileNotFound) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorIo{
		Reason: reason}}
}

func (e ErrorIo) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorJson{
		Reason: reason}}
}

func (e ErrorJson) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorManifest{
		Reason: reason}}
}

func (e ErrorManifest) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorManifestNotFound{
		Reason: reason}}
}

func (e ErrorManifestNotFound) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorNotSupported{
		Reason: reason}}
}

func (e ErrorNotSupported) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorOther{
		Reason: reason}}
}

func (e ErrorOther) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorRemoteManifest{
		Reason: reason}}
}

func (e ErrorRemoteManifest) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorResourceNotFound{
		Reason: reason}}
}

func (e ErrorResourceNotFound) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorRwLock{}}
}

func (e ErrorRwLock) destroy() {
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
	return &Error{err: &ErrorSignature{
		Reason: reason}}
}

func (e ErrorSignature) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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
	return &Error{err: &ErrorVerify{
		Reason: reason}}
}

func (e ErrorVerify) destroy() {
	FfiDestroyerString{}.Destroy(e.Reason)
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

type FfiConverterError struct{}

var FfiConverterErrorINSTANCE = FfiConverterError{}

func (c FfiConverterError) Lift(eb RustBufferI) *Error {
	return LiftFromRustBuffer[*Error](c, eb)
}

func (c FfiConverterError) Lower(value *Error) C.RustBuffer {
	return LowerIntoRustBuffer[*Error](c, value)
}

func (c FfiConverterError) Read(reader io.Reader) *Error {
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
		panic(fmt.Sprintf("Unknown error code %d in FfiConverterError.Read()", errorID))
	}
}

func (c FfiConverterError) Write(writer io.Writer, value *Error) {
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
		panic(fmt.Sprintf("invalid error value `%v` in FfiConverterError.Write", value))
	}
}

type FfiDestroyerError struct{}

func (_ FfiDestroyerError) Destroy(value *Error) {
	switch variantValue := value.err.(type) {
	case ErrorAssertion:
		variantValue.destroy()
	case ErrorAssertionNotFound:
		variantValue.destroy()
	case ErrorDecoding:
		variantValue.destroy()
	case ErrorEncoding:
		variantValue.destroy()
	case ErrorFileNotFound:
		variantValue.destroy()
	case ErrorIo:
		variantValue.destroy()
	case ErrorJson:
		variantValue.destroy()
	case ErrorManifest:
		variantValue.destroy()
	case ErrorManifestNotFound:
		variantValue.destroy()
	case ErrorNotSupported:
		variantValue.destroy()
	case ErrorOther:
		variantValue.destroy()
	case ErrorRemoteManifest:
		variantValue.destroy()
	case ErrorResourceNotFound:
		variantValue.destroy()
	case ErrorRwLock:
		variantValue.destroy()
	case ErrorSignature:
		variantValue.destroy()
	case ErrorVerify:
		variantValue.destroy()
	default:
		_ = variantValue
		panic(fmt.Sprintf("invalid error value `%v` in FfiDestroyerError.Destroy", value))
	}
}

type SeekMode uint

const (
	SeekModeStart   SeekMode = 1
	SeekModeEnd     SeekMode = 2
	SeekModeCurrent SeekMode = 3
)

type FfiConverterSeekMode struct{}

var FfiConverterSeekModeINSTANCE = FfiConverterSeekMode{}

func (c FfiConverterSeekMode) Lift(rb RustBufferI) SeekMode {
	return LiftFromRustBuffer[SeekMode](c, rb)
}

func (c FfiConverterSeekMode) Lower(value SeekMode) C.RustBuffer {
	return LowerIntoRustBuffer[SeekMode](c, value)
}
func (FfiConverterSeekMode) Read(reader io.Reader) SeekMode {
	id := readInt32(reader)
	return SeekMode(id)
}

func (FfiConverterSeekMode) Write(writer io.Writer, value SeekMode) {
	writeInt32(writer, int32(value))
}

type FfiDestroyerSeekMode struct{}

func (_ FfiDestroyerSeekMode) Destroy(value SeekMode) {
}

type SigningAlg uint

const (
	SigningAlgEs256   SigningAlg = 1
	SigningAlgEs256k  SigningAlg = 2
	SigningAlgEs384   SigningAlg = 3
	SigningAlgEs512   SigningAlg = 4
	SigningAlgPs256   SigningAlg = 5
	SigningAlgPs384   SigningAlg = 6
	SigningAlgPs512   SigningAlg = 7
	SigningAlgEd25519 SigningAlg = 8
)

type FfiConverterSigningAlg struct{}

var FfiConverterSigningAlgINSTANCE = FfiConverterSigningAlg{}

func (c FfiConverterSigningAlg) Lift(rb RustBufferI) SigningAlg {
	return LiftFromRustBuffer[SigningAlg](c, rb)
}

func (c FfiConverterSigningAlg) Lower(value SigningAlg) C.RustBuffer {
	return LowerIntoRustBuffer[SigningAlg](c, value)
}
func (FfiConverterSigningAlg) Read(reader io.Reader) SigningAlg {
	id := readInt32(reader)
	return SigningAlg(id)
}

func (FfiConverterSigningAlg) Write(writer io.Writer, value SigningAlg) {
	writeInt32(writer, int32(value))
}

type FfiDestroyerSigningAlg struct{}

func (_ FfiDestroyerSigningAlg) Destroy(value SigningAlg) {
}

type SignerCallback interface {
	Sign(data []byte) ([]byte, *Error)
}

type FfiConverterCallbackInterfaceSignerCallback struct {
	handleMap *concurrentHandleMap[SignerCallback]
}

var FfiConverterCallbackInterfaceSignerCallbackINSTANCE = FfiConverterCallbackInterfaceSignerCallback{
	handleMap: newConcurrentHandleMap[SignerCallback](),
}

func (c FfiConverterCallbackInterfaceSignerCallback) Lift(handle uint64) SignerCallback {
	val, ok := c.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}
	return val
}

func (c FfiConverterCallbackInterfaceSignerCallback) Read(reader io.Reader) SignerCallback {
	return c.Lift(readUint64(reader))
}

func (c FfiConverterCallbackInterfaceSignerCallback) Lower(value SignerCallback) C.uint64_t {
	return C.uint64_t(c.handleMap.insert(value))
}

func (c FfiConverterCallbackInterfaceSignerCallback) Write(writer io.Writer, value SignerCallback) {
	writeUint64(writer, uint64(c.Lower(value)))
}

type FfiDestroyerCallbackInterfaceSignerCallback struct{}

func (FfiDestroyerCallbackInterfaceSignerCallback) Destroy(value SignerCallback) {}

type uniffiCallbackResult C.int8_t

const (
	uniffiIdxCallbackFree               uniffiCallbackResult = 0
	uniffiCallbackResultSuccess         uniffiCallbackResult = 0
	uniffiCallbackResultError           uniffiCallbackResult = 1
	uniffiCallbackUnexpectedResultError uniffiCallbackResult = 2
	uniffiCallbackCancelled             uniffiCallbackResult = 3
)

type concurrentHandleMap[T any] struct {
	handles       map[uint64]T
	currentHandle uint64
	lock          sync.RWMutex
}

func newConcurrentHandleMap[T any]() *concurrentHandleMap[T] {
	return &concurrentHandleMap[T]{
		handles: map[uint64]T{},
	}
}

func (cm *concurrentHandleMap[T]) insert(obj T) uint64 {
	cm.lock.Lock()
	defer cm.lock.Unlock()

	cm.currentHandle = cm.currentHandle + 1
	cm.handles[cm.currentHandle] = obj
	return cm.currentHandle
}

func (cm *concurrentHandleMap[T]) remove(handle uint64) {
	cm.lock.Lock()
	defer cm.lock.Unlock()

	delete(cm.handles, handle)
}

func (cm *concurrentHandleMap[T]) tryGet(handle uint64) (T, bool) {
	cm.lock.RLock()
	defer cm.lock.RUnlock()

	val, ok := cm.handles[handle]
	return val, ok
}

//export c2pa_cgo_dispatchCallbackInterfaceSignerCallbackMethod0
func c2pa_cgo_dispatchCallbackInterfaceSignerCallbackMethod0(uniffiHandle C.uint64_t, data C.RustBuffer, uniffiOutReturn *C.RustBuffer, callStatus *C.RustCallStatus) {
	handle := uint64(uniffiHandle)
	uniffiObj, ok := FfiConverterCallbackInterfaceSignerCallbackINSTANCE.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}

	res, err :=
		uniffiObj.Sign(
			FfiConverterBytesINSTANCE.Lift(GoRustBuffer{
				inner: data,
			}),
		)

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			*callStatus = C.RustCallStatus{
				code: C.int8_t(uniffiCallbackUnexpectedResultError),
			}
			return
		}

		*callStatus = C.RustCallStatus{
			code:     C.int8_t(uniffiCallbackResultError),
			errorBuf: FfiConverterErrorINSTANCE.Lower(err),
		}
		return
	}

	*uniffiOutReturn = FfiConverterBytesINSTANCE.Lower(res)
}

var UniffiVTableCallbackInterfaceSignerCallbackINSTANCE = C.UniffiVTableCallbackInterfaceSignerCallback{
	sign: (C.UniffiCallbackInterfaceSignerCallbackMethod0)(C.c2pa_cgo_dispatchCallbackInterfaceSignerCallbackMethod0),

	uniffiFree: (C.UniffiCallbackInterfaceFree)(C.c2pa_cgo_dispatchCallbackInterfaceSignerCallbackFree),
}

//export c2pa_cgo_dispatchCallbackInterfaceSignerCallbackFree
func c2pa_cgo_dispatchCallbackInterfaceSignerCallbackFree(handle C.uint64_t) {
	FfiConverterCallbackInterfaceSignerCallbackINSTANCE.handleMap.remove(uint64(handle))
}

func (c FfiConverterCallbackInterfaceSignerCallback) register() {
	C.uniffi_c2pa_fn_init_callback_vtable_signercallback(&UniffiVTableCallbackInterfaceSignerCallbackINSTANCE)
}

type Stream interface {
	ReadStream(length uint64) ([]byte, *Error)

	SeekStream(pos int64, mode SeekMode) (uint64, *Error)

	WriteStream(data []byte) (uint64, *Error)
}

type FfiConverterCallbackInterfaceStream struct {
	handleMap *concurrentHandleMap[Stream]
}

var FfiConverterCallbackInterfaceStreamINSTANCE = FfiConverterCallbackInterfaceStream{
	handleMap: newConcurrentHandleMap[Stream](),
}

func (c FfiConverterCallbackInterfaceStream) Lift(handle uint64) Stream {
	val, ok := c.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}
	return val
}

func (c FfiConverterCallbackInterfaceStream) Read(reader io.Reader) Stream {
	return c.Lift(readUint64(reader))
}

func (c FfiConverterCallbackInterfaceStream) Lower(value Stream) C.uint64_t {
	return C.uint64_t(c.handleMap.insert(value))
}

func (c FfiConverterCallbackInterfaceStream) Write(writer io.Writer, value Stream) {
	writeUint64(writer, uint64(c.Lower(value)))
}

type FfiDestroyerCallbackInterfaceStream struct{}

func (FfiDestroyerCallbackInterfaceStream) Destroy(value Stream) {}

//export c2pa_cgo_dispatchCallbackInterfaceStreamMethod0
func c2pa_cgo_dispatchCallbackInterfaceStreamMethod0(uniffiHandle C.uint64_t, length C.uint64_t, uniffiOutReturn *C.RustBuffer, callStatus *C.RustCallStatus) {
	handle := uint64(uniffiHandle)
	uniffiObj, ok := FfiConverterCallbackInterfaceStreamINSTANCE.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}

	res, err :=
		uniffiObj.ReadStream(
			FfiConverterUint64INSTANCE.Lift(length),
		)

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			*callStatus = C.RustCallStatus{
				code: C.int8_t(uniffiCallbackUnexpectedResultError),
			}
			return
		}

		*callStatus = C.RustCallStatus{
			code:     C.int8_t(uniffiCallbackResultError),
			errorBuf: FfiConverterErrorINSTANCE.Lower(err),
		}
		return
	}

	*uniffiOutReturn = FfiConverterBytesINSTANCE.Lower(res)
}

//export c2pa_cgo_dispatchCallbackInterfaceStreamMethod1
func c2pa_cgo_dispatchCallbackInterfaceStreamMethod1(uniffiHandle C.uint64_t, pos C.int64_t, mode C.RustBuffer, uniffiOutReturn *C.uint64_t, callStatus *C.RustCallStatus) {
	handle := uint64(uniffiHandle)
	uniffiObj, ok := FfiConverterCallbackInterfaceStreamINSTANCE.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}

	res, err :=
		uniffiObj.SeekStream(
			FfiConverterInt64INSTANCE.Lift(pos),
			FfiConverterSeekModeINSTANCE.Lift(GoRustBuffer{
				inner: mode,
			}),
		)

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			*callStatus = C.RustCallStatus{
				code: C.int8_t(uniffiCallbackUnexpectedResultError),
			}
			return
		}

		*callStatus = C.RustCallStatus{
			code:     C.int8_t(uniffiCallbackResultError),
			errorBuf: FfiConverterErrorINSTANCE.Lower(err),
		}
		return
	}

	*uniffiOutReturn = FfiConverterUint64INSTANCE.Lower(res)
}

//export c2pa_cgo_dispatchCallbackInterfaceStreamMethod2
func c2pa_cgo_dispatchCallbackInterfaceStreamMethod2(uniffiHandle C.uint64_t, data C.RustBuffer, uniffiOutReturn *C.uint64_t, callStatus *C.RustCallStatus) {
	handle := uint64(uniffiHandle)
	uniffiObj, ok := FfiConverterCallbackInterfaceStreamINSTANCE.handleMap.tryGet(handle)
	if !ok {
		panic(fmt.Errorf("no callback in handle map: %d", handle))
	}

	res, err :=
		uniffiObj.WriteStream(
			FfiConverterBytesINSTANCE.Lift(GoRustBuffer{
				inner: data,
			}),
		)

	if err != nil {
		// The only way to bypass an unexpected error is to bypass pointer to an empty
		// instance of the error
		if err.err == nil {
			*callStatus = C.RustCallStatus{
				code: C.int8_t(uniffiCallbackUnexpectedResultError),
			}
			return
		}

		*callStatus = C.RustCallStatus{
			code:     C.int8_t(uniffiCallbackResultError),
			errorBuf: FfiConverterErrorINSTANCE.Lower(err),
		}
		return
	}

	*uniffiOutReturn = FfiConverterUint64INSTANCE.Lower(res)
}

var UniffiVTableCallbackInterfaceStreamINSTANCE = C.UniffiVTableCallbackInterfaceStream{
	readStream:  (C.UniffiCallbackInterfaceStreamMethod0)(C.c2pa_cgo_dispatchCallbackInterfaceStreamMethod0),
	seekStream:  (C.UniffiCallbackInterfaceStreamMethod1)(C.c2pa_cgo_dispatchCallbackInterfaceStreamMethod1),
	writeStream: (C.UniffiCallbackInterfaceStreamMethod2)(C.c2pa_cgo_dispatchCallbackInterfaceStreamMethod2),

	uniffiFree: (C.UniffiCallbackInterfaceFree)(C.c2pa_cgo_dispatchCallbackInterfaceStreamFree),
}

//export c2pa_cgo_dispatchCallbackInterfaceStreamFree
func c2pa_cgo_dispatchCallbackInterfaceStreamFree(handle C.uint64_t) {
	FfiConverterCallbackInterfaceStreamINSTANCE.handleMap.remove(uint64(handle))
}

func (c FfiConverterCallbackInterfaceStream) register() {
	C.uniffi_c2pa_fn_init_callback_vtable_stream(&UniffiVTableCallbackInterfaceStreamINSTANCE)
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

func (c FfiConverterOptionalString) Lower(value *string) C.RustBuffer {
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
		return GoRustBuffer{
			inner: C.uniffi_c2pa_fn_func_sdk_version(_uniffiStatus),
		}
	}))
}

func Version() string {
	return FfiConverterStringINSTANCE.Lift(rustCall(func(_uniffiStatus *C.RustCallStatus) RustBufferI {
		return GoRustBuffer{
			inner: C.uniffi_c2pa_fn_func_version(_uniffiStatus),
		}
	}))
}
