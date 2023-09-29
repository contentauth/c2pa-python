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

mod error;
mod json_api;
mod signer_info;

pub use error::{Error, Result};
pub use json_api::*;
pub use signer_info::SignerInfo;

/// Returns the version of this library
fn version() -> String {
    String::from(env!("CARGO_PKG_VERSION"))
}

/// Returns the version of the c2pa SDK used in this library
fn sdk_version() -> String {
    String::from(c2pa::VERSION)
}

uniffi::include_scaffolding!("c2pa");
