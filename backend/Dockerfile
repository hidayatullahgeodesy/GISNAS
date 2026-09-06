FROM golang:1.22-bookworm

WORKDIR /app

# Install GDAL (for ogr2ogr with PostgreSQL driver) first to leverage Docker layer caching
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin && rm -rf /var/lib/apt/lists/*

# Initialize Go modules and copy source
COPY go.mod ./
COPY *.go ./

# Fetch dependencies and build
RUN go mod tidy
RUN go build -o /gisnas-backend .

EXPOSE 8080

CMD [ "/gisnas-backend" ]

