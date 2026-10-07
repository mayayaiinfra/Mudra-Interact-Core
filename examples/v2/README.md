# v2 CLI examples

These files contain synthetic 21-point landmarks only. They do not contain
camera images, identifiers or cultural labels.

```powershell
.venv\Scripts\mudra-interact.exe recognize --input examples/v2/frame.json
.venv\Scripts\mudra-interact.exe recognize --input examples/v2/batch.json --stabilize
.venv\Scripts\mudra-interact.exe recognize --input examples/v2/batch.json --stabilize --emit-event --consent --confirm
```

The single frame remains a local candidate because temporal stability requires
three distinct frames and the configured hold time. The batch is a complete
v2 envelope with three increasing frame IDs and monotonic times. Event output
is image-free and requires the two explicit flags shown above.
