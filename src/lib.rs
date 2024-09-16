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

/// This module exports a C2PA library
use std::env;
use std::sync::RwLock;

pub use c2pa::SigningAlg;

/// these all need to be public so that the uniffi macro can see them
mod error;
pub use error::{Error, Result};
#[cfg(feature = "v1")]
mod json_api;
#[cfg(feature = "v1")]
pub use json_api::{read_file, read_ingredient_file, sign_file};
#[cfg(feature = "v1")]
mod signer_info;
#[cfg(feature = "v1")]
pub use signer_info::{CallbackSigner, SignerCallback, SignerConfig, SignerInfo};
mod callback_signer;
pub use callback_signer::{CallbackSigner, SignerCallback};
mod streams;
pub use streams::{SeekMode, Stream, StreamAdapter};

#[cfg(test)]
mod test_stream;

uniffi::include_scaffolding!("c2pa");

/// Returns the version of this library
fn version() -> String {
    String::from(env!("CARGO_PKG_VERSION"))
}

/// Returns the version of the C2PA library
pub fn sdk_version() -> String {
    format!(
        "{}/{} {}/{}",
        env!("CARGO_PKG_NAME"),
        env!("CARGO_PKG_VERSION"),
        c2pa::NAME,
        c2pa::VERSION
    )
}

pub struct Reader {
    reader: RwLock<c2pa::Reader>,
}

impl Reader {
    pub fn new() -> Self {
        Self {
            reader: RwLock::new(c2pa::Reader::default()),
        }
    }

    pub fn from_stream(&self, format: &str, stream: &dyn Stream) -> Result<String> {
        // uniffi doesn't allow mutable parameters, so we we use an adapter
        let mut stream = StreamAdapter::from(stream);
        let reader = c2pa::Reader::from_stream(format, &mut stream)?;
        let json = reader.to_string();
        if let Ok(mut st) = self.reader.try_write() {
            *st = reader;
        } else {
            return Err(Error::RwLock);
        };
        Ok(json)
    }

    pub fn json(&self) -> Result<String> {
        if let Ok(st) = self.reader.try_read() {
            Ok(st.json())
        } else {
            Err(Error::RwLock)
        }
    }

    pub fn resource_to_stream(&self, uri: &str, stream: &dyn Stream) -> Result<u64> {
        if let Ok(reader) = self.reader.try_read() {
            let mut stream = StreamAdapter::from(stream);
            let size = reader.resource_to_stream(uri, &mut stream)?;
            Ok(size as u64)
        } else {
            Err(Error::RwLock)
        }
    }
}

pub struct Builder {
    // The RwLock is needed because uniffi doesn't allow a mutable self parameter
    builder: RwLock<c2pa::Builder>,
}

impl Builder {
    /// Create a new builder
    ///
    /// Uniffi does not support constructors that return errors
    pub fn new() -> Self {
        Self {
            builder: RwLock::new(c2pa::Builder::default()),
        }
    }

    /// Create a new builder using the Json manifest definition
    pub fn with_json(&self, json: &str) -> Result<()> {
        if let Ok(mut builder) = self.builder.try_write() {
            *builder = c2pa::Builder::from_json(json)?;
        } else {
            return Err(Error::RwLock);
        };
        Ok(())
    }

    /// Add a resource to the builder
    pub fn add_resource(&self, uri: &str, stream: &dyn Stream) -> Result<()> {
        if let Ok(mut builder) = self.builder.try_write() {
            let mut stream = StreamAdapter::from(stream);
            builder.add_resource(uri, &mut stream)?;
        } else {
            return Err(Error::RwLock);
        };
        Ok(())
    }

    pub fn add_ingredient(
        &self,
        ingredient_json: &str,
        format: &str,
        stream: &dyn Stream,
    ) -> Result<()> {
        if let Ok(mut builder) = self.builder.try_write() {
            let mut stream = StreamAdapter::from(stream);
            builder.add_ingredient_from_stream(ingredient_json, format, &mut stream)?;
        } else {
            return Err(Error::RwLock);
        };
        Ok(())
    }

    /// Write the builder to the destination stream as an archive
    pub fn to_archive(&self, dest: &dyn Stream) -> Result<()> {
        if let Ok(mut builder) = self.builder.try_write() {
            let mut dest = StreamAdapter::from(dest);
            builder.to_archive(&mut dest)?;
        } else {
            return Err(Error::RwLock);
        };
        Ok(())
    }

    /// Create a new builder from an archive
    pub fn from_archive(&self, source: &dyn Stream) -> Result<()> {
        if let Ok(mut builder) = self.builder.try_write() {
            let mut source = StreamAdapter::from(source);
            *builder = c2pa::Builder::from_archive(&mut source)?;
        } else {
            return Err(Error::RwLock);
        };
        Ok(())
    }

    /// Sign an asset and write the result to the destination stream
    pub fn sign(
        &self,
        signer: &CallbackSigner,
        format: &str,
        source: &dyn Stream,
        dest: &dyn Stream,
    ) -> Result<Vec<u8>> {
        // uniffi doesn't allow mutable parameters, so we we use an adapter
        let mut source = StreamAdapter::from(source);
        let mut dest = StreamAdapter::from(dest);
        if let Ok(mut builder) = self.builder.try_write() {
            let signer = (*signer).signer();
            Ok(builder.sign(signer, format, &mut source, &mut dest)?)
        } else {
            Err(Error::RwLock)
        }
    }

    /// Sign an asset and write the result to the destination stream
    pub fn sign_file(&self, signer: &CallbackSigner, source: &str, dest: &str) -> Result<Vec<u8>> {
        if let Ok(mut builder) = self.builder.try_write() {
            let signer = (*signer).signer();
            Ok(builder.sign_file(signer, source, dest)?)
        } else {
            Err(Error::RwLock)
        }
    }
}
