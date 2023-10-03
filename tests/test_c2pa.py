
# Copyright 2023 Adobe. All rights reserved.
# This file is licensed to you under the Apache License,
# Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
# or the MIT license (http://opensource.org/licenses/MIT),
# at your option.
# Unless required by applicable law or agreed to in writing,
# this software is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR REPRESENTATIONS OF ANY KIND, either express or
# implied. See the LICENSE-MIT and LICENSE-APACHE files for the
# specific language governing permissions and limitations under
# each license.

import c2pa_python as c2pa
import pytest

def test_version():
    assert c2pa.version() == "0.2.0"

def test_sdk_version():
    assert c2pa.sdk_version() == "0.26.0"


def test_verify_from_file():
    json_store = c2pa.verify_from_file_json("tests/fixtures/C.jpg", None) 
    assert not "validation_status" in json_store

def test_verify_from_file_no_store():
    with pytest.raises(c2pa.Error.Sdk) as err:  
        json_store = c2pa.verify_from_file_json("tests/fixtures/A.jpg", None) 
    assert str(err.value) == "no JUMBF data found"  
 