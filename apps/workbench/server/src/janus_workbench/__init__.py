"""The Janus workbench server: documents, page images, inspection and spec runs over HTTP.

It holds no extraction logic. Every answer comes from one `janus_pdf` function, and every PDF
is parsed in a worker process that the server can stop.
"""
