FROM golang:1.21-bullseye

WORKDIR /app

# Initialize Go modules
COPY go.mod ./
COPY *.go ./

# Run go mod tidy to automatically fetch dependencies and generate go.sum
RUN go mod tidy

# Install GDAL (for ogr2ogr with PostgreSQL driver)
RUN apt-get update && apt-get install -y gdal-bin

# Build the application
RUN go build -o /gisnas-backend

EXPOSE 8080

CMD [ "/gisnas-backend" ]
