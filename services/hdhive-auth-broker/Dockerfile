FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /hdhive-auth-broker ./cmd/server

FROM alpine:3.24
RUN apk add --no-cache ca-certificates wget
COPY --from=build /hdhive-auth-broker /usr/local/bin/hdhive-auth-broker
ENV LISTEN_ADDR=:8080
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/hdhive-auth-broker"]
