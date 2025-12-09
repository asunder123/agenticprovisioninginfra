resource "aws_iam_role" "s3_read_access_role" {
  name               = "s3-read-access-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role_policy.json
}

data "aws_iam_policy_document" "assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_policy" "s3_read_access_policy" {
  name        = "s3-read-access-policy"
  description = "Provides read access to all S3 buckets"
  policy      = data.aws_iam_policy_document.s3_read_access_policy.json
}

data "aws_iam_policy_document" "s3_read_access_policy" {
  statement {
    actions   = ["s3:Get*", "s3:List*"]
    resources = ["arn:aws:s3:::*"]
  }
}

resource "aws_iam_role_policy_attachment" "s3_read_access_policy_attachment" {
  policy_arn = aws_iam_policy.s3_read_access_policy.arn
  role       = aws_iam_role.s3_read_access_role.name
}