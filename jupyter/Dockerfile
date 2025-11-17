FROM quay.io/jupyter/minimal-notebook:python-3.13

# Install git as root first
USER root
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Switch to jovyan and setup workspace
USER jovyan
WORKDIR /home/jovyan/work

# Install uv and copy requirements  
RUN pip install uv
COPY pyproject.toml /home/jovyan/work/pyproject.toml

# Install dependencies
USER root
RUN runuser -u jovyan -- uv pip install --system -r /home/jovyan/work/pyproject.toml

# Ensure ownership and create kernel
RUN chown -R jovyan:users /home/jovyan/work
RUN python -m ipykernel install --name=uv-env --display-name "UV Environment"

# Configure jupytext for automatic pairing
RUN mkdir -p /home/jovyan/.jupyter && \
    echo 'c.ContentsManager.default_jupytext_formats = "ipynb,py:percent"' > /home/jovyan/.jupyter/jupyter_notebook_config.py && \
    chown -R jovyan:users /home/jovyan/.jupyter

# Create libs directory structure
RUN mkdir -p /home/jovyan/featuremesh-demos/libs/helpers && \
    chown -R jovyan:users /home/jovyan/featuremesh-demos

USER jovyan

ENV PYTHONPATH="${PYTHONPATH}:/home/jovyan/featuremesh-demos:/home/jovyan/featuremesh-demos/libs"

WORKDIR /home/jovyan/featuremesh-demos

EXPOSE 8880

# Start notebook with token for easy access
CMD start-notebook.sh \
    --port 8880 \
    --ServerApp.ip=0.0.0.0 \
    --allow-root \
    --ServerApp.token='' \
    --ServerApp.password='' \
    --KernelSpecManager.default_kernel_name="uv-env"