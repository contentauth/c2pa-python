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

use std::io::{Read, Seek, SeekFrom, Write};
use std::sync::RwLock;

use std::io::Cursor;

use crate::{Error, Result, SeekMode, Stream};

pub struct TestStream {
    stream: RwLock<Cursor<Vec<u8>>>,
}

impl TestStream {
    pub fn new() -> Self {
        Self {
            stream: RwLock::new(Cursor::new(Vec::new())),
        }
    }
    pub fn from_memory(data: Vec<u8>) -> Self {
        Self {
            stream: RwLock::new(Cursor::new(data)),
        }
    }
}

impl Stream for TestStream {
    fn read_stream(&self, length: u64) -> Result<Vec<u8>> {
        if let Ok(mut stream) = RwLock::write(&self.stream) {
            let mut data = vec![0u8; length as usize];
            let bytes_read = stream.read(&mut data).map_err(|e| Error::Io {
                reason: e.to_string(),
            })?;
            data.truncate(bytes_read);
            //println!("read_stream: {:?}, pos {:?}", data.len(), (*stream).position());
            Ok(data)
        } else {
            Err(Error::Other {
                reason: "RwLock".to_string(),
            })
        }
    }

    fn seek_stream(&self, pos: i64, mode: SeekMode) -> Result<u64> {
        if let Ok(mut stream) = RwLock::write(&self.stream) {
            //stream.seek(SeekFrom::Start(pos as u64)).map_err(|e| StreamError::Io{ reason: e.to_string()})?;
            let whence = match mode {
                SeekMode::Start => SeekFrom::Start(pos as u64),
                SeekMode::End => SeekFrom::End(pos as i64),
                SeekMode::Current => SeekFrom::Current(pos as i64),
            };
            stream.seek(whence).map_err(|e| Error::Io {
                reason: e.to_string(),
            })
        } else {
            Err(Error::Other {
                reason: "RwLock".to_string(),
            })
        }
    }

    fn write_stream(&self, data: Vec<u8>) -> Result<u64> {
        if let Ok(mut stream) = RwLock::write(&self.stream) {
            let len = stream.write(&data).map_err(|e| Error::Io {
                reason: e.to_string(),
            })?;
            Ok(len as u64)
        } else {
            Err(Error::Other {
                reason: "RwLock".to_string(),
            })
        }
    }
}
