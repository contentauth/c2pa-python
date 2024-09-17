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

use c2pa::SigningAlg;

use crate::Result;

/// Defines the callback interface for a signer
pub trait SignerCallback: Send + Sync {
    /// Sign the given bytes and return the signature
    fn sign(&self, bytes: Vec<u8>) -> Result<Vec<u8>>;
}

/// This is a wrapper around the CallbackSigner for Python
///
/// Uniffi callbacks are only supported as a method in a structure, so this is a workaround
pub struct CallbackSigner {
    signer: c2pa::CallbackSigner,
}

impl CallbackSigner {
    pub fn new(
        callback: Box<dyn SignerCallback>,
        alg: SigningAlg,
        certs: Vec<u8>,
        ta_url: Option<String>,
    ) -> Self {
        // When this closure is called it will call the sign method on the python callback
        let python_signer = move |_context: *const (), data: &[u8]| {
            callback
                .sign(data.to_vec())
                .map_err(|e| c2pa::Error::BadParam(e.to_string()))
        };

        let mut signer = c2pa::CallbackSigner::new(python_signer, alg, certs);
        if let Some(url) = ta_url {
            signer = signer.set_tsa_url(url);
        }
        Self { signer }
    }

    /// The python Builder wrapper sign function calls this
    pub fn signer(&self) -> &c2pa::CallbackSigner {
        &self.signer
    }
}
