# perception_pkg

## Depth camera topic policy

`perception_pkg/perception_pkg/depth_camera_node.py` uses **relative publish topic defaults**:

- `color/image_raw`
- `depth/image_raw`
- `depth/image_colormap`
- `color/camera_info`
- `depth/camera_info`

Production topic names are finalized in launch (`bringup/launch/perception.launch.py`) via namespace/remapping, for example:

- `/dori/camera/color/image_raw`
- `/dori/camera/depth/image_raw`
- `/dori/camera/depth/image_colormap`
- `/dori/camera/color/camera_info`
- `/dori/camera/depth/camera_info`

Do not hardcode absolute `/dori/...` camera publish topics inside node code.
