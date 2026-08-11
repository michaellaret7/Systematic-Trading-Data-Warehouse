from dotenv import load_dotenv

from src.config import require
from src.storage.arctic import BALANCE_SHEET_QUARTERLY, connect, read

load_dotenv()

bucket, region = require("S3_BUCKET", "AWS_DEFAULT_REGION")
library = connect()

bs = (
    read(library, BALANCE_SHEET_QUARTERLY, symbols="CRWV")
    .sort("date", descending=True)
    .head(10)
)

