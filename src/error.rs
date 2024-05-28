use thiserror::Error;
pub type Result<T> = std::result::Result<T, Error>;

#[derive(Error, Debug)]
/// Defines all possible errors that can occur in this library
pub enum Error {
    #[error("Assertion {reason}")]
    Assertion { reason: String },
    #[error("AssertionNotFound {reason}")]
    AssertionNotFound { reason: String },
    #[error("Decoding {reason}")]
    Decoding { reason: String },
    #[error("Encoding {reason}")]
    Encoding { reason: String },
    #[error("FileNotFound{reason}")]
    FileNotFound { reason: String },
    #[error("Io {reason}")]
    Io { reason: String },
    #[error("Json {reason}")]
    Json { reason: String },
    #[error("Manifest {reason}")]
    Manifest { reason: String },
    #[error("ManifestNotFound {reason}")]
    ManifestNotFound { reason: String },
    #[error("NotSupported {reason}")]
    NotSupported { reason: String },
    #[error("Other {reason}")]
    Other { reason: String },
    #[error("Remote {reason}")]
    RemoteManifest { reason: String },
    #[error("ResourceNotFound {reason}")]
    ResourceNotFound { reason: String },
    #[error("RwLock")]
    RwLock,
    #[error("Signature {reason}")]
    Signature { reason: String },
    #[error("Verify {reason}")]
    Verify { reason: String },
}

impl Error {
    // Convert c2pa errors to published API errors
    #[allow(unused_variables)]
    pub(crate) fn from_c2pa_error(err: c2pa::Error) -> Self {
        use c2pa::Error::*;
        let err_str = err.to_string();
        match err {
            c2pa::Error::AssertionMissing { url } => Self::AssertionNotFound {
                reason: "".to_string(),
            },
            AssertionInvalidRedaction
            | AssertionRedactionNotFound
            | AssertionUnsupportedVersion => Self::Assertion { reason: err_str },
            ClaimAlreadySigned
            | ClaimUnsigned
            | ClaimMissingSignatureBox
            | ClaimMissingIdentity
            | ClaimVersion
            | ClaimInvalidContent
            | ClaimMissingHardBinding
            | ClaimSelfRedact
            | ClaimDisallowedRedaction
            | UpdateManifestInvalid
            | TooManyManifestStores => Self::Manifest { reason: err_str },
            ClaimMissing { label } => Self::ManifestNotFound { reason: err_str },
            AssertionDecoding(_) | ClaimDecoding => Self::Decoding { reason: err_str },
            AssertionEncoding | XmlWriteError | ClaimEncoding => Self::Encoding { reason: err_str },
            InvalidCoseSignature { coset_error } => Self::Signature { reason: err_str },
            CoseSignatureAlgorithmNotSupported
            | CoseMissingKey
            | CoseX5ChainMissing
            | CoseInvalidCert
            | CoseSignature
            | CoseVerifier
            | CoseCertExpiration
            | CoseCertRevoked
            | CoseInvalidTimeStamp
            | CoseTimeStampValidity
            | CoseTimeStampMismatch
            | CoseTimeStampGeneration
            | CoseTimeStampAuthority
            | CoseSigboxTooSmall
            | InvalidEcdsaSignature => Self::Signature { reason: err_str },
            RemoteManifestFetch(_) | RemoteManifestUrl(_) => {
                Self::RemoteManifest { reason: err_str }
            }
            JumbfNotFound => Self::ManifestNotFound { reason: err_str },
            BadParam(_) | MissingFeature(_) => Self::Other { reason: err_str },
            IoError(_) => Self::Io { reason: err_str },
            JsonError(e) => Self::Json { reason: err_str },
            NotFound | ResourceNotFound(_) | MissingDataBox => {
                Self::ResourceNotFound { reason: err_str }
            }
            FileNotFound(_) => Self::FileNotFound { reason: err_str },
            UnsupportedType => Self::NotSupported { reason: err_str },
            ClaimVerification(_) | InvalidClaim(_) | JumbfParseError(_) => {
                Self::Verify { reason: err_str }
            }
            #[cfg(feature = "add_thumbnails")]
            ImageError => Self::ImageError(err_str),
            _ => Self::Other { reason: err_str },
        }
    }
}

impl From<uniffi::UnexpectedUniFFICallbackError> for Error {
    fn from(err: uniffi::UnexpectedUniFFICallbackError) -> Self {
        Self::Other {
            reason: err.reason.clone(),
        }
    }
}

impl From<c2pa::Error> for Error {
    fn from(err: c2pa::Error) -> Self {
        Self::from_c2pa_error(err)
    }
}

impl From<std::io::Error> for Error {
    fn from(err: std::io::Error) -> Self {
        Self::Io {
            reason: err.to_string(),
        }
    }
}
