FROM public.ecr.aws/lambda/python:3.11

# Copy requirements and install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}
COPY pronote_client.py ${LAMBDA_TASK_ROOT}
COPY calendar_client.py ${LAMBDA_TASK_ROOT}
COPY config.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD ["lambda_function.lambda_handler"]