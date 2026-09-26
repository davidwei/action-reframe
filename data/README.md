# Local data

Keep videos, project configurations, model responses, caches, trial renders, complete renders, and exports here or in an external workspace. All contents except this README are ignored by Git.

Local layout on this machine:

```text
data/workspace -> /home/dwei/longvideo
data/outputs/  # New experiments using configs/ examples
```

The workspace link gives the development server access to existing data without duplicating large videos. It is a machine-local link and will not appear in a clone. It also gives write access to those project settings and outputs; use a separate workspace for isolated changes.

For a separate workspace, place video files at its top level and copy `configs/sailboat_example.json` to `sailboat_example.json` there. Adjust `video` to a filename inside that workspace, `output_dir` to `outputs/sailboat_example`, and the subject/reference settings for the actual footage. Set `LONGVIDEO_WORKSPACE` to that directory before starting the review server. The current UI expects a default `sailboat_example.json` and uses it as the new-project template; removing this assumption is future work.

Do not delete or relocate the linked source workspace while existing jobs are using it. Data migration into a durable project store belongs to the implementation plan.
