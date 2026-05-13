FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt .
RUN pip install -r requirements.txt --quiet

COPY *.py ${LAMBDA_TASK_ROOT}/
COPY profiles/ ${LAMBDA_TASK_ROOT}/profiles/
COPY credentials.json ${LAMBDA_TASK_ROOT}/
COPY token.json ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.lambda_handler"]
