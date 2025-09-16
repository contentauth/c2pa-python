c2pa
====

.. py:module:: c2pa


Submodules
----------

.. toctree::
   :maxdepth: 1

   /api/c2pa/build/index
   /api/c2pa/c2pa/index
   /api/c2pa/lib/index


Exceptions
----------

.. autoapisummary::

   c2pa.C2paError


Classes
-------

.. autoapisummary::

   c2pa.Builder
   c2pa.Reader
   c2pa.C2paSigningAlg
   c2pa.C2paSignerInfo
   c2pa.Signer
   c2pa.Stream


Functions
---------

.. autoapisummary::

   c2pa.sdk_version
   c2pa.read_ingredient_file


Package Contents
----------------

.. py:class:: Builder(manifest_json)

   High-level wrapper for C2PA Builder operations.


   .. py:method:: get_supported_mime_types()
      :classmethod:


      Get the list of supported MIME types for the Builder.
      This method retrieves supported MIME types from the native library.

      :returns: List of supported MIME type strings

      :raises C2paError: If there was an error retrieving the MIME types



   .. py:method:: from_json(manifest_json)
      :classmethod:


      Create a new Builder from a JSON manifest.

      :param manifest_json: The JSON manifest definition

      :returns: A new Builder instance

      :raises C2paError: If there was an error creating the builder



   .. py:method:: from_archive(stream)
      :classmethod:


      Create a new Builder from an archive stream.

      :param stream: The stream containing the archive
                     (any Python stream-like object)

      :returns: A new Builder instance

      :raises C2paError: If there was an error creating the builder from archive



   .. py:method:: close()

      Release the builder resources.

      This method ensures all resources are properly cleaned up,
      even if errors occur during cleanup.
      Errors during cleanup are logged but not raised to ensure cleanup.
      Multiple calls to close() are handled gracefully.



   .. py:method:: set_no_embed()

      Set the no-embed flag.

      When set, the builder will not embed a C2PA manifest store
      into the asset when signing.
      This is useful when creating cloud or sidecar manifests.



   .. py:method:: set_remote_url(remote_url)

      Set the remote URL.

      When set, the builder embeds a remote URL into the asset when signing.
      This is useful when creating cloud based Manifests.

      :param remote_url: The remote URL to set

      :raises C2paError: If there was an error setting the remote URL



   .. py:method:: add_resource(uri, stream)

      Add a resource to the builder.

      :param uri: The URI to identify the resource
      :param stream: The stream containing the resource data
                     (any Python stream-like object)

      :raises C2paError: If there was an error adding the resource



   .. py:method:: add_ingredient(ingredient_json, format, source)

      Add an ingredient to the builder (facade method).
      The added ingredient's source should be a stream-like object
      (for instance, a file opened as stream).

      :param ingredient_json: The JSON ingredient definition
      :param format: The MIME type or extension of the ingredient
      :param source: The stream containing the ingredient data
                     (any Python stream-like object)

      :raises C2paError: If there was an error adding the ingredient
      :raises C2paError.Encoding: If the ingredient JSON contains
          invalid UTF-8 characters



   .. py:method:: add_ingredient_from_stream(ingredient_json, format, source)

      Add an ingredient from a stream to the builder.
      Explicitly named API requiring a stream as input parameter.

      :param ingredient_json: The JSON ingredient definition
      :param format: The MIME type or extension of the ingredient
      :param source: The stream containing the ingredient data
                     (any Python stream-like object)

      :raises C2paError: If there was an error adding the ingredient
      :raises C2paError.Encoding: If the ingredient JSON or format
          contains invalid UTF-8 characters



   .. py:method:: add_ingredient_from_file_path(ingredient_json, format, filepath)

      Add an ingredient from a file path to the builder.
      This is a legacy method.

      .. deprecated:: 0.13.0
         This method is deprecated and will be removed in a future version.
         Use :meth:`add_ingredient` with a file stream instead.

      :param ingredient_json: The JSON ingredient definition
      :param format: The MIME type or extension of the ingredient
      :param filepath: The path to the file containing the ingredient data
                       (can be a string or Path object)

      :raises C2paError: If there was an error adding the ingredient
      :raises C2paError.Encoding: If the ingredient JSON or format
          contains invalid UTF-8 characters
      :raises FileNotFoundError: If the file at the specified path does not exist



   .. py:method:: to_archive(stream)

      Write an archive of the builder to a stream.

      :param stream: The stream to write the archive to
                     (any Python stream-like object)

      :raises C2paError: If there was an error writing the archive



   .. py:method:: sign(signer, format, source, dest = None)

      Sign the builder's content and write to a destination stream.

      :param format: The MIME type or extension of the content
      :param source: The source stream (any Python stream-like object)
      :param dest: The destination stream (any Python stream-like object),
                   opened in w+b (write+read binary) mode.
      :param signer: The signer to use

      :returns: Manifest bytes

      :raises C2paError: If there was an error during signing



   .. py:method:: sign_file(source_path, dest_path, signer)

      Sign a file and write the signed data to an output file.

      :param source_path: Path to the source file. We will attempt
                          to guess the mimetype of the source file based on
                          the extension.
      :param dest_path: Path to write the signed file to
      :param signer: The signer to use

      :returns: Manifest bytes

      :raises C2paError: If there was an error during signing



.. py:exception:: C2paError(message = '')

   Bases: :py:obj:`Exception`


   Exception raised for C2PA errors.


   .. py:attribute:: message
      :value: ''



   .. py:exception:: Assertion

      Bases: :py:obj:`Exception`


      Exception raised for assertion errors.



   .. py:exception:: AssertionNotFound

      Bases: :py:obj:`Exception`


      Exception raised when an assertion is not found.



   .. py:exception:: Decoding

      Bases: :py:obj:`Exception`


      Exception raised for decoding errors.



   .. py:exception:: Encoding

      Bases: :py:obj:`Exception`


      Exception raised for encoding errors.



   .. py:exception:: FileNotFound

      Bases: :py:obj:`Exception`


      Exception raised when a file is not found.



   .. py:exception:: Io

      Bases: :py:obj:`Exception`


      Exception raised for IO errors.



   .. py:exception:: Json

      Bases: :py:obj:`Exception`


      Exception raised for JSON errors.



   .. py:exception:: Manifest

      Bases: :py:obj:`Exception`


      Exception raised for manifest errors.



   .. py:exception:: ManifestNotFound

      Bases: :py:obj:`Exception`


      Exception raised when a manifest is not found.



   .. py:exception:: NotSupported

      Bases: :py:obj:`Exception`


      Exception raised for unsupported operations.



   .. py:exception:: Other

      Bases: :py:obj:`Exception`


      Exception raised for other errors.



   .. py:exception:: RemoteManifest

      Bases: :py:obj:`Exception`


      Exception raised for remote manifest errors.



   .. py:exception:: ResourceNotFound

      Bases: :py:obj:`Exception`


      Exception raised when a resource is not found.



   .. py:exception:: Signature

      Bases: :py:obj:`Exception`


      Exception raised for signature errors.



   .. py:exception:: Verify

      Bases: :py:obj:`Exception`


      Exception raised for verification errors.



.. py:class:: Reader(format_or_path, stream = None, manifest_data = None)

   High-level wrapper for C2PA Reader operations.


   .. py:method:: get_supported_mime_types()
      :classmethod:


      Get the list of supported MIME types for the Reader.
      This method retrieves supported MIME types from the native library.

      :returns: List of supported MIME type strings

      :raises C2paError: If there was an error retrieving the MIME types



   .. py:method:: close()

      Release the reader resources.

      This method ensures all resources are properly cleaned up,
      even if errors occur during cleanup.
      Errors during cleanup are logged but not raised to ensure cleanup.
      Multiple calls to close() are handled gracefully.



   .. py:method:: json()

      Get the manifest store as a JSON string.

      :returns: The manifest store as a JSON string

      :raises C2paError: If there was an error getting the JSON



   .. py:method:: resource_to_stream(uri, stream)

      Write a resource to a stream.

      :param uri: The URI of the resource to write
      :param stream: The stream to write to (any Python stream-like object)

      :returns: The number of bytes written

      :raises C2paError: If there was an error writing the resource to stream



.. py:class:: C2paSigningAlg

   Bases: :py:obj:`enum.IntEnum`


   Supported signing algorithms.


   .. py:attribute:: ES256
      :value: 0



   .. py:attribute:: ES384
      :value: 1



   .. py:attribute:: ES512
      :value: 2



   .. py:attribute:: PS256
      :value: 3



   .. py:attribute:: PS384
      :value: 4



   .. py:attribute:: PS512
      :value: 5



   .. py:attribute:: ED25519
      :value: 6



.. py:class:: C2paSignerInfo(alg, sign_cert, private_key, ta_url)

   Bases: :py:obj:`ctypes.Structure`


   Configuration for a Signer.


.. py:class:: Signer(signer_ptr)

   High-level wrapper for C2PA Signer operations.


   .. py:method:: from_info(signer_info)
      :classmethod:


      Create a new Signer from signer information.

      :param signer_info: The signer configuration

      :returns: A new Signer instance

      :raises C2paError: If there was an error creating the signer



   .. py:method:: from_callback(callback, alg, certs, tsa_url = None)
      :classmethod:


      Create a signer from a callback function.

      :param callback: Function that signs data and returns the signature
      :param alg: The signing algorithm to use
      :param certs: Certificate chain in PEM format
      :param tsa_url: Optional RFC 3161 timestamp authority URL

      :returns: A new Signer instance

      :raises C2paError: If there was an error creating the signer
      :raises C2paError.Encoding: If the certificate data or TSA URL
          contains invalid UTF-8 characters



   .. py:method:: close()

      Release the signer resources.

      This method ensures all resources are properly cleaned up,
      even if errors occur during cleanup.

      .. note::

         Multiple calls to close() are handled gracefully.
         Errors during cleanup are logged but not raised
         to ensure cleanup.



   .. py:method:: reserve_size()

      Get the size to reserve for signatures from this signer.

      :returns: The size to reserve in bytes

      :raises C2paError: If there was an error getting the size



.. py:class:: Stream(file_like_stream)

   .. py:method:: close()

      Release the stream resources.

      This method ensures all resources are properly cleaned up,
      even if errors occur during cleanup.
      Errors during cleanup are logged but not raised to ensure cleanup.
      Multiple calls to close() are handled gracefully.



   .. py:method:: write_to_target(dest_stream)


   .. py:property:: closed
      :type: bool


      Check if the stream is closed.

      :returns: True if the stream is closed, False otherwise
      :rtype: bool


   .. py:property:: initialized
      :type: bool


      Check if the stream is properly initialized.

      :returns: True if the stream is initialized, False otherwise
      :rtype: bool


.. py:function:: sdk_version()

   Returns the underlying c2pa-rs/c2pa-c-ffi version string


.. py:function:: read_ingredient_file(path, data_dir)

   Read a file as C2PA ingredient.
   This creates the JSON string that would be used as the ingredient JSON.

   .. deprecated:: 0.11.0
       This function is deprecated and will be removed in a future version.
       Please use the Reader class for reading C2PA metadata instead.
       Example:
           .. code-block:: python

               with Reader(path) as reader:
                   manifest_json = reader.json()

       To add ingredients to a manifest, please use the Builder class.
       Example:
           .. code-block:: python

               with open(ingredient_file_path, 'rb') as f:
                   builder.add_ingredient(ingredient_json, "image/jpeg", f)

   :param path: Path to the file to read
   :param data_dir: Directory to write binary resources to

   :returns: The ingredient as a JSON string

   :raises C2paError: If there was an error reading the file


