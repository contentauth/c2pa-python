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

# This example shows how to add a do not train assertion to an asset and then verify it

import json
import os
import sys
import c2pa_python as c2pa;

# set up paths to the files we we are using
PROJECT_PATH = os.getcwd()
testFile = os.path.join(PROJECT_PATH,"tests","fixtures","A.jpg")
pemFile = os.path.join(PROJECT_PATH,"tests","fixtures","es256_certs.pem")
keyFile = os.path.join(PROJECT_PATH,"tests","fixtures","es256_private.key")
testOutputFile = os.path.join(PROJECT_PATH,"target","dnt.jpg")

# a little helper function to get a value from a nested dictionary
from functools import reduce
import operator
def getitem(d, key):
    return reduce(operator.getitem, key, d)

print("version = " + c2pa.version())

