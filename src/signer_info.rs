// Copyright 2023 Adobe. All rights reserved.
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

use c2pa::{create_signer, Signer, SigningAlg};
use serde::Deserialize;

use crate::{Error, Result};

/// SignerInfo provides the information needed to create a signer
/// and sign a manifest.
///
/// The signer is created from the signcert and pkey fields.
///
/// The alg field is used to determine the signing algorithm.
///
/// The tsa_url field is optional and is used to specify a timestamp server.
///
#[derive(Clone, Debug, Deserialize)]
pub struct SignerInfo {
    pub signcert: Vec<u8>,
    pub pkey: Vec<u8>,
    pub alg: String,
    pub tsa_url: Option<String>,
}
impl SignerInfo {
    /// Create a SignerInfo from a JSON formatted SignerInfo string
    pub fn from_json(json: &str) -> Result<Self> {
        serde_json::from_str(json).map_err(Error::Json)
    }

    // Returns the signing algorithm converted from string format
    fn alg(&self) -> Result<SigningAlg> {
        self.alg
            .to_lowercase()
            .parse()
            .map_err(|_| Error::Sdk(c2pa::Error::UnsupportedType))
    }

    /// Create a signer from the SignerInfo
    pub fn signer(&self) -> Result<Box<dyn Signer>> {
        create_signer::from_keys(
            &self.signcert,
            &self.pkey,
            self.alg()?,
            self.tsa_url.clone(),
        )
        .map_err(Error::Sdk)
    }
}
