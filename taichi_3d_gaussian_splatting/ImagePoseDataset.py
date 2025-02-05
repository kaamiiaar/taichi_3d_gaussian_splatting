import numpy as np
import pandas as pd
import PIL.Image
import torch
import torch.utils.data
import torchvision
import torchvision.transforms as transforms
from Camera import CameraInfo
from typing import Any
from utils import SE3_to_quaternion_and_translation_torch
from GaussianPointCloudRasterisation import TILE_WIDTH, TILE_HEIGHT

MAX_RESOLUTION_TRAIN=1600

class ImagePoseDataset(torch.utils.data.Dataset):
    """
    A dataset that contains images and poses, and camera intrinsics.
    """

    def __init__(self, dataset_json_path: str):
        super().__init__()
        required_columns = ["image_path", "T_pointcloud_camera",
                            "camera_intrinsics", "camera_height", "camera_width", "camera_id"]
        self.df = pd.read_json(dataset_json_path, orient="records")
        for column in required_columns:
            assert column in self.df.columns, f"column {column} is not in the dataset"

    def __len__(self):
        # return 1 # for debugging
        return len(self.df)

    def _pandas_field_to_tensor(self, field: Any) -> torch.Tensor:
        if isinstance(field, np.ndarray):
            return torch.from_numpy(field)
        elif isinstance(field, list):
            return torch.tensor(field)
        elif isinstance(field, torch.Tensor):
            return field

    @staticmethod
    def _autoscale_image_and_camera_info(image: torch.Tensor, camera_info: CameraInfo):
        if camera_info.camera_height <= MAX_RESOLUTION_TRAIN and camera_info.camera_width <= MAX_RESOLUTION_TRAIN:
            return image, camera_info
        image = transforms.functional.resize(image, size=1024, max_size=1600, antialias=True)
        _, camera_height, camera_width = image.shape
        scale_x = camera_width / camera_info.camera_width
        scale_y = camera_height / camera_info.camera_height
        camera_width = camera_width - camera_width % TILE_WIDTH
        camera_height = camera_height - camera_height % TILE_HEIGHT
        image = image[:3, :camera_height, :camera_width].contiguous()
        camera_intrinsics = camera_info.camera_intrinsics
        camera_intrinsics = camera_intrinsics.clone()
        camera_intrinsics[0, 0] *= scale_x
        camera_intrinsics[1, 1] *= scale_y
        camera_intrinsics[0, 2] *= scale_x
        camera_intrinsics[1, 2] *= scale_y
        resized_camera_info = CameraInfo(
            camera_intrinsics=camera_intrinsics,
            camera_height=camera_height,
            camera_width=camera_width,
            camera_id=camera_info.camera_id)
        return image, resized_camera_info

    def __getitem__(self, idx):
        image_path = self.df.iloc[idx]["image_path"]
        T_pointcloud_camera = self._pandas_field_to_tensor(
            self.df.iloc[idx]["T_pointcloud_camera"])
        q_pointcloud_camera, t_pointcloud_camera = SE3_to_quaternion_and_translation_torch(
            T_pointcloud_camera.unsqueeze(0))
        camera_intrinsics = self._pandas_field_to_tensor(
            self.df.iloc[idx]["camera_intrinsics"])
        base_camera_height = self.df.iloc[idx]["camera_height"]
        base_camera_width = self.df.iloc[idx]["camera_width"]
        camera_id = self.df.iloc[idx]["camera_id"]
        image = PIL.Image.open(image_path)
        image = torchvision.transforms.functional.to_tensor(image)
        # use real image size instead of camera_height and camera_width from colmap
        camera_height = image.shape[1]
        camera_width = image.shape[2]
        camera_intrinsics[0, :] = camera_intrinsics[0, :] * \
            camera_width / base_camera_width
        camera_intrinsics[1, :] = camera_intrinsics[1, :] * \
            camera_height / base_camera_height
        # we want image width and height to be always divisible by 16
        # so we crop the image
        camera_width = camera_width - camera_width % TILE_WIDTH
        camera_height = camera_height - camera_height % TILE_HEIGHT
        image = image[:3, :camera_height, :camera_width].contiguous()
        camera_info = CameraInfo(
            camera_intrinsics=camera_intrinsics,
            camera_height=camera_height,
            camera_width=camera_width,
            camera_id=camera_id,
        )
        image, camera_info = ImagePoseDataset._autoscale_image_and_camera_info(image, camera_info)
        return image, q_pointcloud_camera, t_pointcloud_camera, camera_info
