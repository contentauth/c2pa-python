# Security

This C2PA open-source library is maintained in partnership with Adobe. Adobe accepts security reports through its public [Intigriti program](https://app.intigriti.com/programs/adobe/adobepublic/detail). C2PA is listed in the program for vulnerability disclosure, but is not currently eligible for bounty rewards. Adobe continues to accept reports for assets that are not bounty-eligible, including critical findings it considers important.

## Reporting a vulnerability

Please do not create a public GitHub issue for any suspected security vulnerabilities. Details on how to report security vulnerabilities are available on [Adobe's bug bounty program page](https://www.adobe.com/trust/security/bug-bounty.html).


## Vulnerability SLAs

Once we receive an actionable vulnerability (meaning there is an available patch, or a code fix is required), we will acknowledge the vulnerability within 24 hours. Our target SLAs for resolution are:

1. 72 hours for vulnerabilities with a CVSS score of 9.0-10.0
2. 2 weeks for vulnerabilities with a CVSS score of 7.0-8.9

Any vulnerability with a score below 6.9 will be resolved when possible.


## C2PA Vulnerabilities

This library is not meant to address any potential vulnerabilities within the C2PA specification itself. It is only an implementation of the spec as written. Report suspected vulnerabilities within the spec in the [C2PA specification repository](https://github.com/c2pa-org/specifications/issues).
