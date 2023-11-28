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

pub(crate) use c2pa_c::{
    read_file, read_ingredient_file, sdk_version, sign_file, Error, SignerInfo,
};

/// Returns the version of this library
fn version() -> String {
    String::from(env!("CARGO_PKG_VERSION"))
}

uniffi::include_scaffolding!("c2pa");
