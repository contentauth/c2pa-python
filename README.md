# C2PA Go

This is a proof-of-concept of Golang bindings to the C2PA library; it's forked from the Python repo.

### Building

You'll need cargo and go.

```
make
[ ... ]

./dist/go-demo ~/testvids/screenshot-signed.jpg
{
  "active_manifest": "urn:uuid:019cfdc5-8d91-4b2a-bb0d-f94afb9badef",
  "manifests": {
    "urn:uuid:019cfdc5-8d91-4b2a-bb0d-f94afb9badef": {
      "claim_generator": "Aquareum c2patool/0.9.6 c2pa-rs/0.33.1",
      "title": "Video File",
      "format": "image/jpeg",
      "instance_id": "xmp:iid:755324ba-0c38-4d9a-b7c1-be8a41035ac6",
      "thumbnail": {
        "format": "image/jpeg",
        "identifier": "self#jumbf=c2pa.assertions/c2pa.thumbnail.claim.jpeg"
      },
      "ingredients": [],
      "assertions": [
        {
          "label": "c2pa.actions",
          "data": {
            "actions": [
              {
                "action": "c2pa.published"
              }
            ]
          }
        }
      ],
      "signature_info": {
        "alg": "Es256",
        "issuer": "Internet Widgits Pty Ltd",
        "cert_serial_number": "421347483195564801015437680009080750481212048692",
        "time": "2024-08-08T17:36:42+00:00"
      },
      "label": "urn:uuid:019cfdc5-8d91-4b2a-bb0d-f94afb9badef"
    }
  }
}
```