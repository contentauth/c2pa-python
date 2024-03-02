// Copyright 2024 Adobe. All rights reserved.
// This file is licensed to you under the Apache License,
// Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
// or the MIT license (http://opensource.org/licenses/MIT),
// at your option.
// Unless required by applicable law or agreed to in writing,
// this software is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
// implied. See the LICENSE-MIT and LICENSE-APACHE files for the
// specific language governing permissions and limitations under
// each license.

use c2pa::{Signer, SigningAlg};

use crate::Result;


/// Defines the callback interface for a signer
pub trait SignerCallback: Send + Sync {
    /// Read a stream of bytes from the stream
    fn sign(&self, bytes: Vec<u8>) -> Result<Vec<u8>>;
}

/// Configuration for a Signer
#[repr(C)]
pub struct SignerConfig {
    /// Returns the algorithm of the Signer.
    pub alg: c2pa::SigningAlg,

    /// Returns the certificates as a Vec containing a Vec of DER bytes for each certificate.
    pub certs: Vec<u8>,

    /// URL for time authority to time stamp the signature
    pub time_authority_url: Option<String>,

    /// Try to fetch OCSP response for the signing cert if available
    pub use_ocsp: bool,
}

/// Callback signer that uses a callback to sign data
pub struct CallbackSigner {
    callback: Box<dyn SignerCallback>,
    alg: SigningAlg,
    sign_certs: Vec<u8>,
    ta_url: Option<String>,
}

impl CallbackSigner {
    pub fn new(
        callback: Box<dyn SignerCallback>,
        config: SignerConfig,
        // alg: SigningAlg,
        // sign_certs: Vec<u8>,
        // ta_url: Option<String>,
    ) -> Self {
        Self {
            callback,
            alg: config.alg,
            sign_certs: config.certs,
            ta_url: config.time_authority_url,
        }
    }
}

impl Signer for CallbackSigner {
    fn sign(&self, data: &[u8]) -> c2pa::Result<Vec<u8>> {
        self.callback
            .sign(data.to_vec())
            .map_err(|e| c2pa::Error::BadParam(e.to_string()))
    }

    fn alg(&self) -> SigningAlg {
        self.alg
    }

    fn certs(&self) -> c2pa::Result<Vec<Vec<u8>>> {
        let mut pems =
            pem::parse_many(&self.sign_certs).map_err(|e| c2pa::Error::OtherError(Box::new(e)))?;
        Ok(pems.drain(..).map(|p| p.into_contents()).collect())
    }

    fn reserve_size(&self) -> usize {
        20000
    }

    fn time_authority_url(&self) -> Option<String> {
        self.ta_url.clone()
    }
}
