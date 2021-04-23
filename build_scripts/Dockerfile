FROM python:3.7-alpine3.10 AS compile-image
ARG TERRAFORM_VERSION="0.13.6"

ENV BOTO_CONFIG=/dev/null
COPY . /sources/
WORKDIR /sources

RUN wget -q -O terraform.zip https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip \
    && unzip terraform.zip -d /usr/local/bin \
    && rm -rf terraform.zip
RUN apk add --virtual=build bash gcc libffi-dev musl-dev openssl-dev make
RUN ln -s /usr/local/bin/python /usr/bin/python
RUN bash build_scripts/freeze_requirements.sh
RUN bash build_scripts/run_tests.sh
RUN bash build_scripts/build_package.sh
RUN apk del --purge build


FROM python:3.7-alpine3.12
ARG TERRAFORM_VERSION="0.13.6"
ARG VAULT_VERSION="1.7.1"
ARG KUBECTL_VERSION="v0.19.10"
ARG AWS_IAM_AUTHENTICATOR_VERSION="1.13.7/2019-06-11"
ARG HELM_VERSION="v2.16.1"
ARG HELM_FILE_VERSION="v0.90.8"
ARG HELM_DIFF_VERSION="2.11.0%2B5"
ARG AWSCLI_VERSION="1.19.53"


COPY --from=compile-image /sources/dist /dist

RUN adduser kompos -Du 2342 -h /home/kompos \
    && ln -s /usr/local/bin/python /usr/bin/python \
    && apk add --no-cache bash zsh ca-certificates curl jq openssh-client git \
    && apk add --virtual=build gcc libffi-dev musl-dev openssl-dev make \
    # Install kompos python package
    && pip --no-cache-dir install --upgrade /dist/kompos-*.tar.gz \
    && pip --no-cache-dir install --upgrade awscli==${AWSCLI_VERSION} \
    && rm -rf /dist \
    && apk del --purge build \
    && wget -q https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl -O /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && wget -q https://storage.googleapis.com/kubernetes-helm/helm-${HELM_VERSION}-linux-amd64.tar.gz -O - | tar -xzO linux-amd64/helm > /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm \
    && wget -q -O terraform.zip https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip \
    && unzip terraform.zip -d /usr/local/bin \
    && rm -rf terraform.zip \
    && mkdir -p  ~/.terraform.d/plugins && wget -q -O ~/.terraform.d/plugins/terraform-provider-vault https://github.com/amuraru/terraform-provider-vault/releases/download/vault-namespaces/terraform-provider-vault \
    && chmod 0755 ~/.terraform.d/plugins/terraform-provider-vault \
    && wget -q -O vault.zip https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_linux_amd64.zip \
    && unzip vault.zip -d /usr/local/bin \
    && rm -rf vault.zip \
    && wget -q https://amazon-eks.s3-us-west-2.amazonaws.com/${AWS_IAM_AUTHENTICATOR_VERSION}/bin/linux/amd64/aws-iam-authenticator -O /usr/local/bin/aws-iam-authenticator \
    && chmod +x /usr/local/bin/aws-iam-authenticator \
    && wget -q https://github.com/roboll/helmfile/releases/download/${HELM_FILE_VERSION}/helmfile_linux_amd64 -O /usr/local/bin/helmfile \
    && chmod +x /usr/local/bin/helmfile

# install utils under `kompos` user
USER kompos
ENV HOME=/home/kompos
WORKDIR /home/kompos

RUN helm init --client-only

RUN curl -sSL https://github.com/databus23/helm-diff/releases/download/v${HELM_DIFF_VERSION}/helm-diff-linux.tgz | tar xvz -C $(helm home)/plugins


USER root
RUN HELM_HOME=/home/kompos/.helm helm plugin install https://github.com/futuresimple/helm-secrets
RUN HELM_HOME=/home/kompos/.helm helm plugin install https://github.com/rimusz/helm-tiller
RUN chown -R kompos:kompos /home/kompos/.helm


RUN touch /home/kompos/.zshrc

USER kompos
ENV PATH="/home/kompos/bin:${PATH}"
ENV PS1="%d $ "
CMD /bin/zsh
