# vowerp3be

This is the backend for a webapp which will be a multitenant app for an erp solution, using nextjs for frontend and python for backend.

VOW ERP3 Backend python


docker build command 
docker build -t vowerp-backend .

run command 
docker run -d -p 8000:8000 --env-file .env --name vowerp3be vowerp3be-docker

stop container command
docker stop vowerp3be

remove container command
docker rm vowerp3be-docker


 run tests inside the container, you can override the default Docker CMD:
docker build -t vowerp3be-docker .
docker run --rm -it vowerp3be-docker pytest
Alternatively, you can use a command in your Dockerfile or Docker Compose to handle tests, but the simplest approach is to run a container that executes pytest.




using db.py against database.py for sqlmodel

to run the project locally on docker first create a docker network:
command for the same is - docker network create vowerpnet
to check if docker network is created from before - docker network ls

to run docker in the said network 
docker run -d \
  --name vowerp-backend \
  --network vowerpnet \
  --env-file .env \
  -p 8000:8000 \
  vowerp-backend


  