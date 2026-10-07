import json
import logging
import os
import sys
import time
from pathlib import Path

# Add the project root to the sys.path so we can import from src
sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.pipeline import answer_question

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def seed_cache(data_path: str = "data/common_questions.json", delay_seconds: int = 2):
    path = Path(data_path)
    if not path.exists():
        logger.error(f"Data file not found at {data_path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    logger.info(f"Found {len(questions)} questions to seed.")
    
    success_count = 0
    skip_count = 0
    error_count = 0

    for i, question in enumerate(questions):
        logger.info(f"Processing ({i+1}/{len(questions)}): {question}")
        
        try:
            # We skip execution if the query is already cached (just in case the script is restarted)
            # The rewrite_query logic might change the string slightly, but running it again is safe anyway.
            # However, for true idempotency without relying on the exact rewrite string, we let pipeline handle it.
            
            # answer_question automatically checks the cache and caches if missed.
            answer = answer_question(question)
            
            if hasattr(answer, "text"):
                logger.info(f"Successfully processed. Answer length: {len(answer.text)}")
            elif isinstance(answer, tuple) or hasattr(answer, "session_id"):
                # AnswerWithSession or tuple
                logger.info("Successfully processed.")
            else:
                 logger.info(f"Successfully processed. Answer type: {type(answer)}")

            success_count += 1
            
            # Respect rate limits for external APIs
            if i < len(questions) - 1:
                logger.info(f"Sleeping for {delay_seconds} seconds to respect API rate limits...")
                time.sleep(delay_seconds)
                
        except Exception as e:
            logger.error(f"Failed to process question: '{question}'. Error: {e}")
            error_count += 1
            
            # Larger backoff on error
            time.sleep(delay_seconds * 2)

    logger.info(f"Seeding complete! Success: {success_count}, Errors: {error_count}")


if __name__ == "__main__":
    # You can configure delay as needed
    seed_cache()
