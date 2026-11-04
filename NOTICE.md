# Third-party notices

## Ren'Py API data

`src/renpy_language_server/data/renpy_api.json` is derived from the `src/renpy.json` file in
[`renpy/vscode-language-renpy`](https://github.com/renpy/vscode-language-renpy).

The original data was converted from nested categories into a flat table, and
each entry keeps only its name, kind, argument list, Python type, category and
documentation. Names, signatures and documentation are otherwise unchanged.

`src/renpy_language_server/data/completion.json` also includes the `keyword_values` table
from `src/renpyauto.json` in the same project. The surrounding screen-element,
property, transform and transition lists are a curated snapshot of Ren'Py's
public screen language.

```text
The MIT License

Original work Copyright (c) 2018 Daniel Luque <danielluque14@gmail.com>
Modified work Copyright (c) 2024 Tom Rothamel <pytom@bishoujo.us>

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```
