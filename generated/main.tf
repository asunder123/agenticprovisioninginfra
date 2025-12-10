provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "lg7892" {
  bucket = "lg7892"
  acl    = "private"
}

resource "aws_s3_bucket_website_configuration" "lg7892" {
  bucket = aws_s3_bucket.lg7892.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "error.html"
  }
}

resource "aws_s3_object" "index" {
  bucket = aws_s3_bucket.lg7892.id
  key    = "index.html"
  content = "<html><body><h1>Login Page</h1></body></html>"
  content_type = "text/html"
  acl    = "public-read"
}

resource "aws_s3_object" "error" {
  bucket = aws_s3_bucket.lg7892.id
  key    = "error.html"
  content = "<html><body><h1>Error</h1></body></html>"
  content_type = "text/html"
  acl    = "public-read"
}