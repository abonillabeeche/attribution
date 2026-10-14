# Third-party materials and license exceptions

NVIDIA Attribution project code is licensed under [Apache-2.0](LICENSE).
The materials below retain their respective notices and terms.

## shadcn/ui

The WebUI components in
[the frontend UI component directory](blueprint/src/attribution_blueprint/webui/frontend/src/components/ui),
together with supporting hooks, utilities, and styles, include code derived
from [shadcn/ui](https://github.com/shadcn-ui/ui) and modified for NVIDIA
Attribution. The upstream code is licensed under MIT
([original license](https://github.com/shadcn-ui/ui/blob/6ea6856f5a1082d4d9c231559b6bc3ee73827493/LICENSE.md)):

```text
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## OpenAPI Generator templates

The templates in [service/service-app/openapi/templates](service/service-app/openapi/templates)
are derived from [OpenAPI Generator](https://github.com/OpenAPITools/openapi-generator).
Their [upstream Apache-2.0 license and copyright notices](service/service-app/openapi/templates/LICENSE)
are preserved. Local changes provide the project header and adapt generated
client arguments. Generated client code uses the project's Apache-2.0 license.

## Contributor Covenant

[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) is adapted from Contributor Covenant
3.0 and retains its Creative Commons Attribution-ShareAlike 4.0 license and
attribution.

## Installed dependencies

Python and JavaScript dependencies retain their own licenses. Package manifests
and lockfiles record the dependencies used by the Service, Library, Blueprint,
and interactive documentation. Review the license files and notices distributed
with those dependencies when redistributing a built application or documentation
site. The project's Apache-2.0 license does not replace those terms.

The Blueprint WebUI and interactive walkthrough builds write
`assets/THIRD_PARTY_NOTICES.txt`. It reproduces this document and the license
and NOTICE texts of the JavaScript packages bundled into that build. Keep that
file with the built assets when redistributing them.
