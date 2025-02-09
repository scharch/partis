### Installation

Partis can be installed either [with Docker](#installation-with-docker) or [from scratch](#installation-from-scratch).

[Using Docker](#installation-with-docker) makes the installation process much easier, because it installs specific versions of each dependency in a controlled environment. The process of running, however, is then a bit less convenient since you're inside Docker (the use of batch systems, for instance, will be difficult).

Installing [without Docker](#installation-from-scratch), on the other hand, will require more effort to install (or more accurately, a higher chance of descent into dependency hell), but once installed it'll be easier to use. The closer your system is to the latest Ubuntu, the easier this process will be (RHEL variants and macOS typically work without too much trouble).

If you want to make simulated samples, you'll also need to [install some R packages](#simulation).

#### Installation with Docker

Docker can be installed using the instructions [here](https://docs.docker.com). If you're new to Docker, start with the official [quick start](https://docs.docker.com/get-started/) guide. Then,

```
sudo docker pull psathyrella/partis  # pull partis image from docker hub
sudo docker run -it --name container-1 -v ~:/host/home psathyrella/partis /bin/bash  # start up a container from this image
```
The `sudo` may not be necessary for some systems. With `docker run`, we create a new container from (i.e. instance of) the partis image. The `-v` mounts your home directory on the host machine to the path `/host/home` inside the container, so we can easily extract results.

Docker's default escape key is ctrl-p, which unfortunately conflicts with common command line shortcuts. To change this put`{"detachKeys": "ctrl-q,q"}` into the file `~/.docker/config.json` which will swap it to ctrl-q.

When finished, you _don't_ want to just exit and `docker run` again -- this will create a new container.
One solution is to run Docker inside [tmux](https://hackernoon.com/a-gentle-introduction-to-tmux-8d784c404340?gi=70388a0228fb) in which case you can just leave the container open.
Alternatively, you can detach from the container with `ctrl-q q` (or whatever you've remapped ctrl-p q to).
To then reattach to this running container, run `docker attach container-1`.

#### Installation from scratch

To install without Docker, you basically just run the commands in the [Dockerfile](../Dockerfile) (ignoring the `FROM` and `COPY` lines).
In place of `FROM`, you should clone the partis repo and init/update its submodules:
```
git clone git@github.com:psathyrella/partis
git submodule update --init --recursive
```
If you're on a debian variant, run the apt-get install as written.
On other distros, or on macOS, you'll have to figure out the equivalent package names, but after that just swap yum/brew for apt-get.

If you don't have conda installed, follow the full installation instructions [here](https://docs.anaconda.com/anaconda/install/).
Any time you're using conda, it needs to be in your path, for example with `export PATH=<path_to_conda>:$PATH`.
While conda typically works better, you can also install the python packages with pip (you should probably user the `--user` option).

Because conda and pip do not play well with each other, if you've used pip in the past but are going to now use conda, and you won't need pip in the future, you should completely remove `~/.local`.
If you might need pip in the future, you should expect some difficulty with having both conda and pip on the same system.
In most cases you can prevent conda from finding the packages in `~/.local` (and consequently breaking) by setting `export PYTHONNOUSERSITE=True` (see [this issue](https://github.com/conda/conda/issues/448) for some context).
You may also need to `unset LD_LIBRARY_PATH`.

Once conda is installed, run the rest of the commands in the Dockerfile whose lines are marked with `RUN` or `CMD`, except substitute the line `WORKDIR /partis` with `cd partis/`.

In order to avoid polluting your environment, we do not automatically add partis to your path.
Several methods of accomplishing this are described [here](subcommands.md#subcommands).

#### Simulation

By default, partis simulation generates trees using the R packages TreeSim and TreeSimGM, so if not already present they'll need to be installed (along with R).
Alternatively, if you have a list of your own newick trees in a file you can pass this in with `--input-simulation-treefname`, in which case you can avoid R installation entirely.
One way to install R on debian/ubuntu (and thus also within a partis container) is:
```
apt-get install -y dirmngr apt-transport-https ca-certificates software-properties-common gnupg2
# UPDATE maybe should be keyserver.ubuntu.com?
apt-key adv --keyserver keys.gnupg.net --recv-key 'E19F5F87128899B192B1A2C2AD5F960A256A04AF'  # this R installation stuff was in the Dockerfile for a while, but this line was crashing on dockerhub, and it appears that keyservers are just too flakey to use in docker files
add-apt-repository 'deb https://cloud.r-project.org/bin/linux/debian stretch-cran35/'  # this will have to change when anaconda changes debian releases, but the tree sim packages require a more recent version of r than is in the debian repos
apt-get update && apt-get install -y r-base
# UPDATE maybe should have this here somewhere https://mirror.las.iastate.edu/CRAN/
```
Note that TreeSim/TreeSimGM require a much more recent R version than is in the default repos.
Note also that if you instead install R with conda, it replaces your entire compiler toolchain (e.g. screws up where your system looks for gcc) so you probably won't be able to compile anything afterwards.

You can then install the required R packages with:
```
R --vanilla --slave -e 'install.packages(c("TreeSim", "TreeSimGM", "geiger", "MASS"), repos="http://cran.rstudio.com/", dependencies=TRUE)'
```
The default mutation model also requires compilation of an updated (development) version of bpp that's in `packages/bpp-newlik/`:
```
./bin/build.sh with-simulation  # this takes a while, maybe 20-60 minutes
```
However, if you don't much care about mutation model accuracy (in particular, if you don't care about modeling different rates between different bases e.g. A->C vs A->T), you can set `--no-per-base-mutation` and it'll fall back to an older, already-compiled bpp version in `packages/bpp`.

#### MDS Plotting

In order to make the [MDS plots](plotting.md#partition-plots), you need R and the bios2mds package installed:

```
apt-get install xorg libx11-dev libglu1-mesa-dev r-cran-rgl  # may not be necessary, depending on existing R install, but is at least necessary in docker
conda install -y -cr r-rgl r-essentials
unset R_LIBS_SITE
R --vanilla --slave -e 'install.packages(c("class", "bios2mds"), dependencies=T, repos="http://cran.rstudio.com/")'  # this may be all the deps: c("picante", "pspline", "deSolve", "igraph", "TESS", "fpc", "pvclust", "corpcor", "phytools", "mvMORPH", "geiger", "mvtnorm", "glassoFast", "Rmpfr")
```
