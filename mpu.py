from __future__ import annotations

from pydantic import BaseModel
from enum import Enum
from typing import Any
from fastapi import FastAPI

app = FastAPI()


class StorageType(Enum):
    S3 = "S3"
    ABS = "ABS"  # AZURE_BLOB_STORAGE
    ADLS = "ADLS"  # AZURE_DELTA_LAKE_STORAGE_GEN2
    GCS = "GCS"


class Request(BaseModel):
    url: str
    headers: dict[str, Any]


######### create ##########
class CreateRequest(BaseModel):
    path: str
    # Only used for S3 and GCS. Ignored for ABS and ADLS.
    num_parts: int


class CreateResponse(BaseModel):
    # This parameter allows the client to change operations
    # depending on the underlying storage provider.
    type: StorageType
    # For ABS and ADLS, the length will be 1. We can upload
    # multiple chunks by changing a query parameter.
    # For S3 and GCS, the length will be equal to `num_parts`.
    upload: list[Request]
    # For ABS and ADLS, this field is None
    upload_id: str | None


@app.post("/mlflow-artifacts/mpu/create")
def create(request: CreateRequest) -> CreateResponse:
    """
    Initiate an MPU (if necessary) and generates presigned
    URLs for uploading parts, completing
    """
    ...


######### complete #########
# Q. can we complete an MPU using a presigned URL?
# A. No, for S3, we need ETag values to complete an MPU.
#    They are only known after chunks have been uploaded.
class CompleteRequest(BaseModel):
    path: str
    # S3 and GCS need this, but ABS and ADLS don't
    upload_id: str | None
    # ADLS doesn't need chunk IDs, only needs a request to flush previously appended data
    chunk_ids: list[str] | None


class CompleteResponse(BaseModel):
    pass


@app.post("/mlflow-artifacts/mpu/complete")
def complete(request: CompleteRequest) -> CompleteResponse:
    """
    Initiate an MPU (if necessary) and generates presigned
    URLs for uploading parts, completing
    """
    ...


######### abort #########
class AbortRequest(BaseModel):
    # In S3, pre-signed URLs only supports GET and PUT,
    # not DELETE.
    path: str
    # Only required for S3 and GCS
    upload_id: str | None


class AbortResponse(BaseModel):
    pass


@app.post("/mlflow-artifacts/mpu/abort")
def abort(request: AbortRequest) -> AbortResponse:
    """
    Aborts a specified MPU
    """
    ...


######### upload-url #########
class UploadUrlRequest(BaseModel):
    path: str
    part_number: int


class UploadUrlResponse(BaseModel):
    upload: Request


@app.post("/mlflow-artifacts/mpu/upload-url")
def upload_url(request: UploadUrlRequest) -> UploadUrlResponse:
    """
    Regenerates a new presigned URL for retrying a part upload.
    """
    ...
